import pytest
from bikefinder_rag.agent.loop import _detail_year_clarification

@pytest.mark.parametrize('name',['get_catalog_details','search_technical'])
def test_new_tools_cannot_silently_substitute_redirected_year(name):
    calls=[(name,{'model':'Desmo450 Sm','year':2027})]
    assert _detail_year_clarification(calls,'Fiche Ducati Desmo450 Sm de 2026',[]) is not None

@pytest.mark.parametrize('name',['get_catalog_details','search_technical'])
def test_new_tools_use_explicit_year(name):
    calls=[(name,{'model':'Desmo450 Sm','year':2027})]
    assert _detail_year_clarification(calls,'Fiche Ducati Desmo450 Sm de 2027',[]) is None
