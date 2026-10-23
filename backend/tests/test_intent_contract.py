from improved.compiler import QueryPlan
from improved.intent_contract import missing_entity_constraints

CONFIG = [{'fields':['dim_country.country','fact_retail_line.country'],
           'values':{'France':['法国','France'],'Germany':['德国','Germany']}}]


def test_explicit_country_cannot_disappear_from_plan():
    plan = QueryPlan(metrics=['SALES_AMOUNT'], filters=[{'field':'dim_date.year','op':'eq','value':2010}])
    missing = missing_entity_constraints('按年月列出2010年法国销售额',plan,CONFIG)
    assert missing[0]['values'] == ['France']


def test_single_country_must_be_present_in_both_comparison_periods():
    plan = QueryPlan(metrics=['SALES_AMOUNT'], filters=[{'field':'fact_retail_line.country','op':'eq','value':'France'}], comparison_filters=[])
    assert missing_entity_constraints('法国今年比去年销售额变化',plan,CONFIG)[0]['period'] == 'comparison'


def test_multi_country_and_exclusion_are_not_silently_overwritten():
    plan = QueryPlan(metrics=['SALES_AMOUNT'], filters=[{'field':'dim_country.country','op':'in','value':['France','Germany']}])
    assert missing_entity_constraints('法国和德国的销售额',plan,CONFIG) == []
    plan = QueryPlan(metrics=['SALES_AMOUNT'], filters=[{'field':'dim_country.country','op':'ne','value':'France'}])
    assert missing_entity_constraints('除法国外的销售额',plan,CONFIG) == []


def test_no_unconfigured_entities_or_english_substring_matches():
    plan = QueryPlan(metrics=['SALES_AMOUNT'])
    assert missing_entity_constraints('NewFrance地区销量',plan,CONFIG) == []
    assert missing_entity_constraints('加拿大销量',plan,CONFIG) == []


def test_boundaries_and_case_are_normalized():
    plan = QueryPlan(metrics=['SALES_AMOUNT'])
    assert missing_entity_constraints('france的销售额',plan,CONFIG)[0]['values'] == ['France']
