"""Submit a frozen lot sequentially to the real Gradio chat, preserving sessions."""
import argparse,json,time,hashlib,sys
from pathlib import Path
from datetime import datetime,timezone
from gradio_client import Client
from eval_technical_demo import text_answer

def main():
 p=argparse.ArgumentParser();p.add_argument('--pack',type=Path,required=True);p.add_argument('--url',default='http://127.0.0.1:7861/');p.add_argument('--out',type=Path,required=True);p.add_argument('--timeout',type=float,default=150);a=p.parse_args()
 if a.out.exists():raise SystemExit('Refuse overwrite of first pass')
 pack=json.loads(a.pack.read_text());sequence=[dict(c,pass_name='first') for c in pack['cases']]
 sequence += [dict(c,pass_name='warm_repeat') for c in pack['cases'] if c['id'] in ['Q01','Q03','Q12','Q16','Q19','Q22']]
 report={'created_at':datetime.now(timezone.utc).isoformat(),'questions_sha256':hashlib.sha256(a.pack.read_bytes()).hexdigest(),'url':a.url,'results':[],'completed':False,'timeout_seconds':a.timeout,'timing_definition':'submit to complete result; Client setup separate; not time to first token'}
 def save():a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 save()
 for c in sequence:
  t=time.perf_counter();client=Client(a.url,verbose=False,analytics_enabled=False,httpx_kwargs={'timeout':30.0});setup=time.perf_counter()-t;visible=[]
  try:
   for n,turn in enumerate(c['turns'],1):
    row={'id':c['id'],'turn':n,'group':c['group'],'category':c['category'],'pass':c['pass_name'],**turn,'client_setup_seconds':setup if n==1 else 0,'started_at':datetime.now(timezone.utc).isoformat()};print('START',row['pass'],c['id'],n,flush=True)
    start=time.perf_counter();job=None
    try:
     job=client.submit(turn['question'],visible,'',api_name='/chat');visible=job.result(timeout=a.timeout);row['answer']=text_answer(visible);row['visible_history']=visible;row['error']=None
    except Exception as exc:
     row['error']=type(exc).__name__+': '+str(exc)
     if job:
      try:row['cancel_accepted']=job.cancel()
      except Exception as cancel:row['cancel_error']=str(cancel)
     row['server_stop_verified']=False
    row['elapsed_seconds']=time.perf_counter()-start;report['results'].append(row);save()
    print(json.dumps({k:row.get(k) for k in ['id','turn','pass','elapsed_seconds','error']},ensure_ascii=False),flush=True)
    if row['error']:
     report['stopped']='API error: no later submissions; verify server job before resuming';save();return
  finally:client.close()
 report.update(completed=True,finished_at=datetime.now(timezone.utc).isoformat());save()
if __name__=='__main__':main()
