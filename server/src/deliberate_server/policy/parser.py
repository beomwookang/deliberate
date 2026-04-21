"""Recursive descent parser for policy expressions (PRD §5.2).

Grammar (intentionally minimal — no function calls, no loops):

    expr        → or_expr
    or_expr     → and_expr ("or" and_expr)*
    and_expr    → not_expr ("and" not_expr)*
    not_expr    → "not" not_expr | comparison
    comparison  → contains_expr (comp_op contains_expr)?
    contains_expr → primary ("contains" primary)?
    primary     → NUMBER | STRING | BOOLEAN | NULL | field_access | "(" expr ")"
    field_access → IDENT ("." IDENT)*

    comp_op     → "<" | ">" | "<=" | ">=" | "==" | "!="

Tokens:
    NUMBER  — integer or float
    STRING  — single or double quoted
    IDENT   — [a-zA-Z_][a-zA-Z0-9_]*
    BOOLEAN — "true" | "false"
    NULL    — "null"

Security: No eval(), no exec(), no general-purpose execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------


class TokenType(Enum):
    NUMBER = auto()
    STRING = auto()
    IDENT = auto()
    BOOLEAN = auto()
    NULL = auto()
    DOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()
    EQ = auto()
    NE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    CONTAINS = auto()
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: Any
    pos: int


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_KEYWORDS = {
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
    "true": TokenType.BOOLEAN,
    "false": TokenType.BOOLEAN,
    "null": TokenType.NULL,
    "contains": TokenType.CONTAINS,
}

_NUMBER_RE = re.compile(r"-?\d+(\.\d+)?")
_IDENT_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_STRING_RE = re.compile(r"""(?:"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)')""")


class TokenizeError(Exception):
    """Raised when the tokenizer encounters an unexpected character."""


def tokenize(source: str) -> list[Token]:
    """Tokenize a policy expression string into a list of tokens."""
    tokens: list[Token] = []
    i = 0
    n = len(source)

    while i < n:
        # Skip whitespace
        if source[i].isspace():
            i += 1
            continue

        # Two-character operators
        if i + 1 < n:
            two = source[i : i + 2]
            if two == "<=":
                tokens.append(Token(TokenType.LE, "<=", i))
                i += 2
                continue
            if two == ">=":
                tokens.append(Token(TokenType.GE, ">=", i))
                i += 2
                continue
            if two == "==":
                tokens.append(Token(TokenType.EQ, "==", i))
                i += 2
                continue
            if two == "!=":
                tokens.append(Token(TokenType.NE, "!=", i))
                i += 2
                continue

        # Single-character operators
        ch = source[i]
        if ch == "<":
            tokens.append(Token(TokenType.LT, "<", i))
            i += 1
            continue
        if ch == ">":
            tokens.append(Token(TokenType.GT, ">", i))
            i += 1
            continue
        if ch == "(":
            tokens.append(Token(TokenType.LPAREN, "(", i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenType.RPAREN, ")", i))
            i += 1
            continue
        if ch == ".":
            tokens.append(Token(TokenType.DOT, ".", i))
            i += 1
            continue

        # Strings
        m = _STRING_RE.match(source, i)
        if m:
            # Group 1 is double-quoted content, group 2 is single-quoted
            str_val = m.group(1) if m.group(1) is not None else m.group(2)
            tokens.append(Token(TokenType.STRING, str_val, i))
            i = m.end()
            continue

        # Numbers (must check before ident since negative numbers start with -)
        m = _NUMBER_RE.match(source, i)
        if m:
            text = m.group()
            num_val: int | float = float(text) if "." in text else int(text)
            tokens.append(Token(TokenType.NUMBER, num_val, i))
            i = m.end()
            continue

        # Identifiers and keywords
        m = _IDENT_RE.match(source, i)
        if m:
            word = m.group()
            if word in _KEYWORDS:
                tt = _KEYWORDS[word]
                if tt == TokenType.BOOLEAN:
                    tokens.append(Token(tt, word == "true", i))
                elif tt == TokenType.NULL:
                    tokens.append(Token(tt, None, i))
                else:
                    tokens.append(Token(tt, word, i))
            else:
                tokens.append(Token(TokenType.IDENT, word, i))
            i = m.end()
            continue

        msg = f"Unexpected character '{ch}' at position {i} in expression: {source!r}"
        raise TokenizeError(msg)

    tokens.append(Token(TokenType.EOF, None, i))
    return tokens


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


@dataclass
class NumberLit:
    value: int | float


@dataclass
class StringLit:
    value: str


@dataclass
class BoolLit:
    value: bool


@dataclass
class NullLit:
    pass


@dataclass
class FieldAccess:
    parts: list[str]  # e.g. ["amount", "value"]


@dataclass
class BinOp:
    op: str  # "<", ">", "<=", ">=", "==", "!="
    left: Any  # AST node
    right: Any


@dataclass
class ContainsOp:
    left: Any
    right: Any


@dataclass
class AndOp:
    left: Any
    right: Any


@dataclass
class OrOp:
    left: Any
    right: Any


@dataclass
class NotOp:
    operand: Any


# Type alias for AST nodes
ASTNode = (
    NumberLit
    | StringLit
    | BoolLit
    | NullLit
    | FieldAccess
    | BinOp
    | ContainsOp
    | AndOp
    | OrOp
    | NotOp
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Raised when the parser encounters a syntax error."""


class Parser:
    """Recursive descent parser for the policy expression grammar."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, tt: TokenType) -> Token:
        tok = self._current()
        if tok.type != tt:
            msg = f"Expected {tt.name}, got {tok.type.name} ({tok.value!r}) at position {tok.pos}"
            raise ParseError(msg)
        return self._advance()

    def parse(self) -> ASTNode:
        """Parse the token stream and return the AST root."""
        node = self._or_expr()
        if self._current().type != TokenType.EOF:
            tok = self._current()
            msg = f"Unexpected token {tok.type.name} ({tok.value!r}) at position {tok.pos}"
            raise ParseError(msg)
        return node

    def _or_expr(self) -> ASTNode:
        left = self._and_expr()
        while self._current().type == TokenType.OR:
            self._advance()
            right = self._and_expr()
            left = OrOp(left, right)
        return left

    def _and_expr(self) -> ASTNode:
        left = self._not_expr()
        while self._current().type == TokenType.AND:
            self._advance()
            right = self._not_expr()
            left = AndOp(left, right)
        return left

    def _not_expr(self) -> ASTNode:
        if self._current().type == TokenType.NOT:
            self._advance()
            operand = self._not_expr()
            return NotOp(operand)
        return self._comparison()

    def _comparison(self) -> ASTNode:
        left = self._contains_expr()
        comp_ops = {
            TokenType.LT,
            TokenType.GT,
            TokenType.LE,
            TokenType.GE,
            TokenType.EQ,
            TokenType.NE,
        }
        if self._current().type in comp_ops:
            op_tok = self._advance()
            right = self._contains_expr()
            return BinOp(op_tok.value, left, right)
        return left

    def _contains_expr(self) -> ASTNode:
        left = self._primary()
        if self._current().type == TokenType.CONTAINS:
            self._advance()
            right = self._primary()
            return ContainsOp(left, right)
        return left

    def _primary(self) -> ASTNode:
        tok = self._current()

        if tok.type == TokenType.NUMBER:
            self._advance()
            return NumberLit(tok.value)

        if tok.type == TokenType.STRING:
            self._advance()
            return StringLit(tok.value)

        if tok.type == TokenType.BOOLEAN:
            self._advance()
            return BoolLit(tok.value)

        if tok.type == TokenType.NULL:
            self._advance()
            return NullLit()

        if tok.type == TokenType.LPAREN:
            self._advance()
            node = self._or_expr()
            self._expect(TokenType.RPAREN)
            return node

        if tok.type == TokenType.IDENT:
            return self._field_access()

        msg = f"Unexpected token {tok.type.name} ({tok.value!r}) at position {tok.pos}"
        raise ParseError(msg)

    def _field_access(self) -> FieldAccess:
        parts = [self._expect(TokenType.IDENT).value]
        while self._current().type == TokenType.DOT:
            self._advance()
            parts.append(self._expect(TokenType.IDENT).value)
        return FieldAccess(parts)


def parse_expression(source: str) -> ASTNode:
    """Tokenize and parse a policy expression string into an AST."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse()
