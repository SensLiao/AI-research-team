from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest
from research_agent_teams.tools.journal_render import choose_journal, validate_journal_choice, prepare_figure_plan
from research_agent_teams.tools.scientific_figure import ScientificFigureError


PROFILE={'journal_id':'ijms','name':'IJMS','aliases':['International Journal of Molecular Sciences'],
         'official_rule_sources':[{'url':'https://www.mdpi.com/journal/ijms/instructions'}],
         'verification_status':'TEST_FIXTURE','internal_targets':{'raster_dpi':600,'min_label_font_pt':8}}


def test_final_delivery_requires_a_real_question_record():
    with pytest.raises(ScientificFigureError,match='JOURNAL_QUESTION_REQUIRED'):
        choose_journal(render_id='round-1',profile=PROFILE,answer='ijms',question_asked=False)


def test_no_preference_uses_recommendation_without_inventing_confirmation():
    choice=choose_journal(render_id='round-1',profile=PROFILE,answer=None,question_asked=True,
                          recommendation_reason='Plant molecular review fits the supplied scope.')
    assert choice['selection']=='RECOMMENDED_NO_PREFERENCE'
    assert choice['answer'] is None
    validate_journal_choice(choice,PROFILE,'IJMS')


def test_user_choice_is_not_replaced_by_a_different_default():
    with pytest.raises(ScientificFigureError,match='DIFFERENT_JOURNAL_PROFILE_REQUIRED'):
        choose_journal(render_id='round-1',profile=PROFILE,answer='Nature',question_asked=True)


def test_profile_changes_invalidate_an_old_choice():
    choice=choose_journal(render_id='round-1',profile=PROFILE,answer='ijms',question_asked=True)
    with pytest.raises(ScientificFigureError,match='JOURNAL_PROFILE_DRIFT'):
        validate_journal_choice(choice,{**PROFILE,'verification_status':'CHANGED'})
    with pytest.raises(ScientificFigureError,match='FROZEN_JOURNAL_MISMATCH'):
        validate_journal_choice(choice,PROFILE,'other-journal')


def _case(root: Path):
    def put(ref,data):
        p=root/ref;p.parent.mkdir(parents=True,exist_ok=True);b=data.encode();p.write_bytes(b)
        return {'ref':ref,'sha256':hashlib.sha256(b).hexdigest()}
    svg=put('draft/figure.svg','<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 80"><text x="20" y="30" font-size="12">Gene expression</text></svg>')
    evidence=put('draft/basis.txt','Synthetic unit-test scientific statement.');evidence.update(kind='EXTERNAL_EVIDENCE',immutable=True)
    spec={'run_id':root.name,'asset_id':'Fig1','label':'fig:one','purpose':'Schematic','caption':{'text':'A test schematic.','owner_role':'figure-engineer'},
          'accessibility_text':'A gene-expression label.','svg_source':svg,'source_inputs':[evidence],
          'claim_refs':['CLM-1'],'output_stem':'evidence/ANALYZE/r1/Fig1','width_mm':80,'dpi':600,'min_font_pt':8,'journal':'ijms'}
    choice=choose_journal(render_id='round-1',profile=PROFILE,answer='ijms',question_asked=True)
    put('draft/journal.json',json.dumps(PROFILE));put('draft/choice.json',json.dumps(choice));put('draft/Fig1.json',json.dumps(spec))
    plan={'journal_profile_ref':'draft/journal.json','journal_choice_ref':'draft/choice.json','figure_specs':['draft/Fig1.json'],
          'manifest_ref':'evidence/figures.json','available_figure_width_mm':80}
    put('draft/scientific-figures.json',json.dumps(plan))
    return spec,plan


def test_automatic_plan_renders_real_files_then_reuses_unchanged_outputs(tmp_path):
    _case(tmp_path)
    first=prepare_figure_plan(tmp_path,'draft/scientific-figures.json',manuscript_sha256='a'*64,expected_journal='ijms')
    second=prepare_figure_plan(tmp_path,'draft/scientific-figures.json',manuscript_sha256='a'*64,expected_journal='ijms')
    assert first['reused'] is False and second['reused'] is True
    assert first['manifest']==second['manifest']
    assert (tmp_path/'evidence/ANALYZE/r1/Fig1.pdf').read_bytes().startswith(b'%PDF')


def test_cached_output_byte_drift_cannot_pass(tmp_path):
    _case(tmp_path)
    prepare_figure_plan(tmp_path,'draft/scientific-figures.json',manuscript_sha256='a'*64)
    (tmp_path/'evidence/ANALYZE/r1/Fig1.png').write_bytes(b'altered')
    with pytest.raises(ScientificFigureError,match='FIGURE_OUTPUT_DRIFT'):
        prepare_figure_plan(tmp_path,'draft/scientific-figures.json',manuscript_sha256='a'*64)


@pytest.mark.parametrize('field,value,code',[('dpi',300,'FIGURE_PROFILE_MISMATCH'),('width_mm',100,'FIGURE_EXCEEDS_MANUSCRIPT_WIDTH')])
def test_profile_and_actual_manuscript_width_are_enforced(tmp_path,field,value,code):
    spec,_=_case(tmp_path);spec[field]=value;(tmp_path/'draft/Fig1.json').write_text(json.dumps(spec),encoding='utf-8')
    with pytest.raises(ScientificFigureError,match=code):
        prepare_figure_plan(tmp_path,'draft/scientific-figures.json',manuscript_sha256='a'*64)
    assert not (tmp_path/'evidence/ANALYZE').exists()


def test_authoring_calls_the_automatic_plan_before_integrating(monkeypatch,tmp_path):
    from research_agent_teams.operate.modes import manuscript_authoring as mode
    import research_agent_teams.tools.journal_render as jr
    _case(tmp_path);calls=[]
    monkeypatch.setattr(mode,'load_frozen_contract',lambda _: {'manuscript_snapshot_sha256':'a'*64,'venue_profile':{'venue_id':'ijms'}})
    monkeypatch.setattr(mode,'_synthesis_handoff',lambda *_: ([], 'draft/basis.txt',''))
    monkeypatch.setattr(mode,'_direct_audit_payloads',lambda *_: {})
    monkeypatch.setattr(mode,'_asset_manifest_payload',lambda *_: None)
    original=jr.prepare_figure_plan
    def prepare(*args,**kwargs):
        result=original(*args,**kwargs);calls.append(result);return result
    monkeypatch.setattr(jr,'prepare_figure_plan',prepare)
    monkeypatch.setattr(mode,'assign_section_owners',lambda *_: [])
    monkeypatch.setattr(mode,'_artifact_payload',lambda *args,**kwargs: None)
    class AtIntegration(Exception):pass
    def integrate(**kwargs):
        assert kwargs['asset_manifest']['schema_version']=='2.0.0'
        assert calls and calls[0]['figure_count']==1
        raise AtIntegration()
    monkeypatch.setattr(mode,'integrate_manuscript',integrate)
    with pytest.raises(AtIntegration):mode._analyze_dets(tmp_path,'2026-09-05T00:00:00Z')
