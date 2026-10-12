import pytest
from bikefinder_rag.agent.catalog_fast_path import parse_abs_question

@pytest.mark.parametrize('question,year,status,count',[
    ("Quelles motos ont l'ABS en 2000 ?",2000,'standard',False),
    ("Combien de motos de 2025 ont l’ABS de série ?",2025,'standard',True),
    ("Quelles motos de 2025 ont l'ABS en option ?",2025,'optional',False),
])
def test_complete_abs_questions(question,year,status,count):
    result=parse_abs_question(question)
    assert result['min_year']==result['max_year']==year
    assert result['equipment_status']==status and result['count_only']==count

@pytest.mark.parametrize('question',[
    "Quelles motos ont l'ABS en 2000 en France ?",
    "Quelles motos ont l'ABS en 2000 et moins de 200 kg ?",
    "Quelles motos n'ont pas l'ABS en 2000 ?",
    "Quelles motos ont l'ABS en 2000 ou 2001 ?",
    "Quelles motos ont l'ABS ?",
])
def test_extra_constraints_or_negation_never_silently_disappear(question):
    assert parse_abs_question(question) is None
