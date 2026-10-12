#!/usr/bin/env python3
"""Import the frozen enriched catalog into local PostgreSQL, atomically."""
import argparse
import json
from pathlib import Path
from dotenv import load_dotenv
from bikefinder_rag.db.client import get_connection
from bikefinder_rag.catalog.enriched import import_catalog

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    load_dotenv()
    conn=get_connection()
    try:
        result=import_catalog(conn,args.source.resolve())
        from bikefinder_rag.catalog.measures import rebuild
        result['numeric_projection']=rebuild(conn)
        print(json.dumps(result))
    finally:
        conn.close()

if __name__=='__main__':
    main()
