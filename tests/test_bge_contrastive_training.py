import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def pilot(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("bge_training_pilot", scripts / "train_bge_contrastive.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_useful_complementary_section_cannot_be_a_negative(pilot):
    case = dict(supplied_scope_object_ids=["bike"], requested_fields=["front_brake", "rear_brake"],
                gold_passages=[dict(id="front"), dict(id="rear")])
    assert pilot.negative_reason(case, dict(id="rear", object_id="bike", original_text="Freinage : disque")) is None
    # Even an unannotated duplicate of a requested fact must not be mined.
    assert pilot.negative_reason(case, dict(id="equipment", object_id="bike", original_text="Freinage ABS")) is None
    assert pilot.negative_reason(case, dict(id="engine", object_id="bike", original_text="Refroidissement : liquide"))


def test_brand_partition_blocks_year_or_variant_leakage(pilot):
    with pytest.raises(ValueError, match="leakage"):
        pilot.validate_partition({s:[dict(expected_identities=[dict(brand="Honda",object_id=s)])] for s in ["train","test"]})


def test_multiple_positives_do_not_compete_with_each_other(pilot):
    import torch
    e = torch.tensor([[1.,0.],[1.,0.],[1.,0.],[-1.,0.]],requires_grad=True)
    loss=pilot.contrastive_loss(e,[(0,[1,2],[3])])
    # A mistaken softmax across all useful proofs would have loss >= log(2).
    assert loss.item()<1e-5
    loss.backward()
    assert torch.isfinite(e.grad).all()


def test_worst_positive_still_receives_a_learning_signal(pilot):
    import torch
    e=torch.tensor([[1.,0.],[1.,0.],[0.,1.],[.5,.5]],requires_grad=True)
    loss=pilot.contrastive_loss(e,[(0,[1,2],[3])])
    loss.backward()
    assert e.grad[2,0].item()<0  # Gradient descent pulls this second proof toward the query.
    assert e.grad[3,0].item()>0  # Push the explicit distractor away.


def test_training_rejects_a_negative_from_reserved_brand(pilot):
    case=dict(supplied_scope_object_ids=["bike"],requested_fields=["seat"],gold_passages=[dict(id="p")],
              positive_evidence=[dict(id="p",original_text="Hauteur de selle : 800 mm")],
              expected_facts=[dict(passage_id="p",quotes=["Hauteur de selle : 800 mm"])],
              negative_evidence=[dict(id="n",object_id="other",brand="Reserved",original_text="other")])
    with pytest.raises(ValueError, match="leakage"):
        pilot.validate_training_data({"train":[case]},{"brands":{"train":["Training"]}})
