"""Run the actual Gradio app with observation and a bounded Jev spending ledger.

No changes to prompts, routing, model arguments or returned answers. The only
intervention is to refuse a remote request before exceeding the campaign cap.
Use only after approval of the question/excerpt scope and campaign budget.
"""
import argparse,contextvars,hashlib,json,os,subprocess,sys,time,uuid,threading
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--port',type=int,default=7861);p.add_argument('--budget',type=float,default=.5);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 from dotenv import load_dotenv
 load_dotenv(ROOT/'.env')
 settings={'AGENT_BACKEND':'ollama','OLLAMA_MODEL':'mistral-small3.2','BIKEFINDER_JEV_ROUTER':'1','BIKEFINDER_JEV_RAG':'1','BIKEFINDER_CATALOG_RESEARCH':'0','BIKEFINDER_CATALOG_EXPERIMENT':'0','BIKEFINDER_CATALOG_FAST_PATH':'0','JEV_ROUTER_TIMEOUT_SECONDS':'5','CATALOG_SYNTHESIS_TIMEOUT_SECONDS':'30','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','GRADIO_ANALYTICS_ENABLED':'False'}
 os.environ.update(settings)
 from bikefinder_rag.embeddings import embedder
 from bikefinder_rag.agent import loop,jev_router
 from compare_mistral_jev import Spending
 assert embedder.MODEL_NAME=='BAAI/bge-m3' and embedder.MODEL_REVISION=='5617a9f61b028005a4858fdac845db406aefb181'
 current=contextvars.ContextVar('evaluation_record',default=None)
 ledger=a.out/'spending.json'
 def save_spending():ledger.write_text(json.dumps({'ceiling_usd':a.budget,'debit_usd':spending.debit,'records':spending.records},ensure_ascii=False,indent=2)+'\n')
 spending=Spending(a.budget,save_spending)
 if ledger.exists():spending.records=json.loads(ledger.read_text())['records']
 save_spending();lock=threading.Lock()
 import requests
 original_post=requests.post
 def observed_post(*args,**kwargs):
  url=str(args[0] if args else kwargs.get('url'));payload=kwargs.get('json',{});record=current.get();event={'url':url,'model':payload.get('model')}
  if url!=jev_router.URL or payload.get('model')!=jev_router.MODEL:raise RuntimeError('Campaign permits only the existing Jev decision endpoint')
  # Twice the verified public prompt tariff and conservative byte bound.
  # Missing cost remains reserved; all responses are accounted for.
  with lock:reservation=spending.reserve(jev_router.MODEL,payload,.084/1e6,0,0)
  t=time.perf_counter()
  try:
   response=original_post(*args,**kwargs);event['status']=response.status_code
   try:
    body=response.json();event.update({k:body[k] for k in ['usage','cost','cost_details'] if k in body})
    with lock:spending.settle(reservation,body)
   except ValueError:pass
   return response
  except Exception as exc:event['error']=type(exc).__name__;raise
  finally:
   event['seconds']=time.perf_counter()-t;event['reserved_usd']=reservation['reserved_usd'];event['debit_usd']=reservation['debit_usd']
   if record is not None:record['http_calls'].append(event)
 requests.post=observed_post
 original_run=loop.run_agent
 def observed_run(conn,client,user_message,history=None,**kwargs):
  record={'id':uuid.uuid4().hex,'question':user_message,'started_at':datetime.now(timezone.utc).isoformat(),'http_calls':[],'history_messages':len(history or [])};token=current.set(record);t=time.perf_counter()
  try:
   answer,updated=original_run(conn,client,user_message,history,**kwargs)
   record['answer']=answer;record['metadata']={k:v for k,v in updated[-1].items() if k.startswith('_catalog_')} if updated else {}
   info=embedder._get_model.cache_info();record['embedder_loaded']=info.currsize>0
   if info.currsize:
    loaded=embedder._get_model();record['embedder_device']=str(loaded.device);record['embedder_class']=type(loaded).__name__
   return answer,updated
  except Exception as exc:record['error']=type(exc).__name__+': '+str(exc);raise
  finally:
   record['server_seconds']=time.perf_counter()-t;current.reset(token)
   (a.out/(record['id']+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n')
 loop.run_agent=observed_run
 from bikefinder_rag.app import launch_chatbot
 metadata={'pid':os.getpid(),'started_at':datetime.now(timezone.utc).isoformat(),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'settings':settings,'embedding_model':embedder.MODEL_NAME,'embedding_revision':embedder.MODEL_REVISION,'source_hashes':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((ROOT/'src/bikefinder_rag').rglob('*.py'))},'observer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'pricing_source':'https://openrouter.ai/typesafe/jev-1.13/api','pricing_checked_at':'2026-10-15','public_prompt_price_usd_per_million':.042,'reservation_prompt_rate_usd_per_million':.084,'note':'Isolated current-code Gradio instance; observation and spending cap only. Existing user instance preserved. No fine-tuned adapter loaded.'}
 (a.out/'runtime.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
 launch_chatbot(server_port=a.port,inbrowser=False)
if __name__=='__main__':main()
