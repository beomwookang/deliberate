#!/bin/bash

python3 -c "import hashlib; print(hashlib.sha256('SmZ-5ETlbm4v-sGgwSd33SE2VMbBbxxdQt0dvR2U8hs'.encode()).hexdigest())" | xargs -I{} docker exec deliberate-postgres-1 psql -U deliberate -c "UPDATE applications SET api_key_hash = '{}' WHERE id = 'default';"

export DELIBERATE_SERVER_URL=http://localhost:4000                      
export DELIBERATE_API_KEY=SmZ-5ETlbm4v-sGgwSd33SE2VMbBbxxdQt0dvR2U8hs     
export DELIBERATE_UI_URL=http://localhost:3000 
echo $DELIBERATE_API_KEY

# uv run python agent.py
uv run python dogfood.py