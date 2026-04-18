"""APScheduler timeout worker entry point.

Polls for pending approvals that have exceeded their timeout_at, and processes
escalation or failure per the matched policy rule. See PRD §6.2 (Timeout Worker).

Currently an empty loop — job scheduling is implemented in M2.
"""

import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler


def run() -> None:
    scheduler = BlockingScheduler()

    # No jobs added yet — this is the M2 milestone.
    # The worker will poll for timed-out approvals and process escalations.

    def shutdown(signum: int, frame: object) -> None:
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print("deliberate-worker: starting (no jobs scheduled yet)")
    scheduler.start()


if __name__ == "__main__":
    run()
