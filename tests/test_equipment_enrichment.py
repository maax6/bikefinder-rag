import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import enrich_equipment as enrichment


def case(text='ABS', section='Équipement de série'):
    return {'id':'case-1','object_id':'object-1','source_url':'https://example.test/source',
            'equipment':'ABS','passages':[{'id':'row-1','section':section,'text':text}]}


def test_local_answer_cannot_clear_an_ambiguous_source():
    c = case('ABS + CBS en option')
    h = enrichment.model.input_hash(c)
    result = enrichment.decide(c, {h:{'status':'optional','confidence':1}}, {h:{'status':'standard'}}, 'pass2')
    assert result['status'] == 'unknown'
    assert result['stage'] == 'source_review'
    assert result['passages'] == c['passages']


def test_explicit_source_option_takes_priority_over_uncertain_or_wrong_models():
    c = case('ABS en option')
    h = enrichment.model.input_hash(c)
    result = enrichment.decide(c, {h:{'status':'optional','confidence':.5}}, {h:{'status':'standard'}}, 'pass2')
    assert result['status'] == 'optional'
    assert result['stage'] == 'code_literal_evidence'
    assert result['passages'] == c['passages']


def test_valid_models_do_not_rewrite_literal_source_facts():
    c = case('ABS en option')
    h = enrichment.model.input_hash(c)
    result = enrichment.decide(c, {h:{'status':'optional','confidence':.5}}, {h:{'status':'optional'}}, 'pass2')
    assert result['status'] == 'optional'
    assert result['stage'] == 'code_literal_evidence'


def test_missing_models_remain_unknown_instead_of_fabricating_fitment():
    result = enrichment.decide(case(section='Moteur'), {}, {}, 'pass2')
    assert result['status'] == 'unknown'
    assert 'mistral:model_error' in result['reasons']


def test_export_preserves_entire_source_and_silence_does_not_mean_absence(tmp_path, monkeypatch):
    monkeypatch.setattr(enrichment.model, 'OUT', tmp_path)
    monkeypatch.setattr(enrichment.model, 'INSTRUCTION', enrichment.model.INSTRUCTION)
    monkeypatch.setattr(enrichment.model, 'CRITERIA', enrichment.model.CRITERIA)
    source = {'id':'object-1','url':'https://example.test/source','brand':'Honda','model':'Test','year':2000,
              'spec_rows':[{'section':'Performances','label':'Autonomie estimée','value':'400 km calculée mais non vérifiée'}],
              'raw_specs':{'Autonomie estimée':'400 km calculée mais non vérifiée'},'collection':{'response_sha256':'original'}}
    frozen = json.dumps({'records':[source]},ensure_ascii=False).encode()
    (tmp_path/'dataset.json').write_bytes(frozen)
    (tmp_path/'cases.json').write_text('[]')
    enrichment.finalize(tmp_path,'pass2')
    assert (tmp_path/'dataset.json').read_bytes() == frozen
    with sqlite3.connect(tmp_path/'pass2/catalogue.enriched.sqlite3') as c:
        raw, digest = c.execute('SELECT record,source_sha256 FROM objects').fetchone()
        assert json.loads(raw) == source
        assert hashlib.sha256(raw.encode()).hexdigest() == digest
        status, stage = c.execute("SELECT status,stage FROM equipment WHERE equipment='ABS'").fetchone()
        assert (status,stage) == ('unknown','code_no_mention')
