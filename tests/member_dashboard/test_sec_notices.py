import pytest
from member_dashboard.sec_notices import notice_summary, person_name, canonical_notice_name


def xml(rows=''):
    return '<edgarSubmission xmlns="http://www.sec.gov/edgar/ownership"><submissionType>144</submissionType><nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>SATYA NADELLA</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>'+rows+'</edgarSubmission>'


def test_notice_uses_proposed_units_value_and_approximate_date():
    result=notice_summary(xml('<securitiesInformation><noOfUnitsSold>86525</noOfUnitsSold><aggregateMarketValue>43893267.25</aggregateMarketValue><approxSaleDate>09/01/2026</approxSaleDate></securitiesInformation><securitiesSoldInPast3Months><noOfUnitsSold>999999</noOfUnitsSold></securitiesSoldInPast3Months>'))
    assert result=='Satya Nadella proposed selling **86,525 shares** (~**$43.9M**) around **Sep 1, 2026**.'
    assert 'before' not in result and '999,999' not in result


def test_notice_preserves_multiple_sale_rows_and_missing_date():
    result=notice_summary(xml('<securitiesInformation><noOfUnitsSold>1000</noOfUnitsSold><approxSaleDate>09/01/2026</approxSaleDate></securitiesInformation><securitiesInformation><noOfUnitsSold>2000</noOfUnitsSold></securitiesInformation>'))
    assert '**1,000 shares**' in result and '**2,000 shares**' in result
    assert 'sale date not provided' in result


@pytest.mark.parametrize('raw',[xml(),xml('<securitiesInformation><noOfUnitsSold>NaN</noOfUnitsSold></securitiesInformation>'),'<html>Access refused</html>','<!DOCTYPE x [<!ENTITY y "x">]>'+xml()])
def test_invalid_notice_has_no_generic_fallback(raw):
    assert notice_summary(raw) is None


@pytest.mark.parametrize('raw,expected',[('NADELLA SATYA','Satya Nadella'),('Hood Amy','Amy Hood'),('Smith, Jane Ann','Jane Ann Smith'),('Smith John Jr.','John Smith Jr.'),('Example Holdings LLC','Example Holdings LLC')])
def test_sec_owner_names_are_first_name_first(raw,expected):
    assert person_name(raw,last_first=True)==expected


def test_natural_name_is_not_reversed():
    assert person_name('SATYA NADELLA')=='Satya Nadella'
    assert person_name('John Smith, Jr.')=='John Smith Jr.'
    assert person_name('Smith, John, Jr.',last_first=True)=='John Smith Jr.'


def test_notice_order_uses_same_person_form4_identity():
    assert canonical_notice_name('Althoff Judson proposed selling **10,000 shares**.', ['ALTHOFF JUDSON'])=='Judson Althoff proposed selling **10,000 shares**.'
    assert canonical_notice_name('Satya Nadella proposed selling **86,525 shares**.', ['NADELLA SATYA'])=='Satya Nadella proposed selling **86,525 shares**.'
