#!/bin/bash
python3 /app/patch.py
exec sh /app/docker/prod_entrypoint.sh "$@"
