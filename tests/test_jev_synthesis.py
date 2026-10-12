from unittest.mock import Mock
import requests
from bikefinder_rag.agent import jev_router as router

PLAN={'models':[{'brand':'BMW','model':'R 1150 GS'}],'identity':{'year':2000},'fields':['autonomy_km']}
ROW={'id':'x','brand':'BMW','model':'R 1150 GS','year':2000,'source_url':'https://source.test/2000',
     'spec_rows':[{'section':'Performances','label':'Autonomie estimée','value':'440 km calculée mais non vérifiée'}]}

def setup(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','fake-test-only')
    monkeypatch.setattr(router,'get_catalog_details',lambda *args:[ROW])
    monkeypatch.setattr(router,'render_details',lambda *args:'440 km calculée mais non vérifiée — https://source.test/2000')

def response(body):
    r=Mock();r.json.return_value=body;return r

def test_model_timeout_returns_source_facts_without_tool_loop(monkeypatch):
    setup(monkeypatch);post=Mock(side_effect=requests.ReadTimeout('timeout'));monkeypatch.setattr(router.requests,'post',post)
    answer=router.synthesize_complex(None,'Explique les limites',PLAN)
    assert 'délai prévu' in answer and 'calculée mais non vérifiée' in answer
    assert post.call_count==1
    assert post.call_args.kwargs['timeout']==30
    assert 'tools' not in post.call_args.kwargs['json']

def test_unsupported_generated_claim_is_replaced_with_source(monkeypatch):
    setup(monkeypatch)
    post=Mock(side_effect=[response({'message':{'content':'L’autonomie est mesurée à 440 km.'}}),response({'answers':{'supported':{'choice':'no','confidence':.99}}})])
    monkeypatch.setattr(router.requests,'post',post)
    answer=router.synthesize_complex(None,'Explique les limites',PLAN)
    assert 'calculée mais non vérifiée' in answer and 'est mesurée' not in answer

def test_supported_bounded_synthesis_keeps_source(monkeypatch):
    setup(monkeypatch);text='Autonomie calculée mais non vérifiée : 440 km [source](https://source.test/2000)'
    monkeypatch.setattr(router.requests,'post',Mock(side_effect=[response({'message':{'content':text}}),response({'answers':{'supported':{'choice':'yes','confidence':.99}}})]))
    assert router.synthesize_complex(None,'Explique les limites',PLAN)==text

def test_invented_source_url_is_rejected_before_gate(monkeypatch):
    setup(monkeypatch);post=Mock(return_value=response({'message':{'content':'Source https://invented.test/'}}));monkeypatch.setattr(router.requests,'post',post)
    assert '440 km calculée mais non vérifiée' in router.synthesize_complex(None,'Explique',PLAN)
    assert post.call_count==1

def test_busy_synthesis_does_not_queue_another_generation(monkeypatch):
    setup(monkeypatch);post=Mock();monkeypatch.setattr(router.requests,'post',post)
    router.SYNTHESIS_SLOT.acquire()
    try:answer=router.synthesize_complex(None,'Explique',PLAN)
    finally:router.SYNTHESIS_SLOT.release()
    assert 'disponibles immédiatement' in answer
    post.assert_not_called()
