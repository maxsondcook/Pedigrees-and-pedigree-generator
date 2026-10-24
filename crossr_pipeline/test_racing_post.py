from crossr_pipeline import racing_post as rp


def test_parse_result():
    assert rp.parse_result("Smarty Jones (USA) - 2001") == {"name": "Smarty Jones", "country": "USA", "year": 2001}
    assert rp.parse_result("Frankel (GB)  -  2008")["country"] == "GB"
    assert rp.parse_result("Some Horse - 1999") == {"name": "Some Horse", "country": "", "year": 1999}
    assert rp.parse_result("Horses") is None


def test_pick_candidates_prefers_suffix_then_window():
    results = [
        {"name": "Storm Cat", "country": "USA", "year": 1983},
        {"name": "Storm Cat", "country": "GB", "year": 1995},
        {"name": "Storm Cats Kitten", "country": "USA", "year": 2001},
    ]
    sire = {"key": "STORM CAT", "suffix": "", "yob_range": (1970, 1990)}
    assert [r["year"] for r in rp.pick_candidates(results, sire)] == [1983]
    sire = {"key": "STORM CAT", "suffix": "GB", "yob_range": None}
    assert [r["country"] for r in rp.pick_candidates(results, sire)] == ["GB"]


def test_fee_rows_dedupes_and_flags_private():
    payload = {"props": {"pageProps": {"initialState": {"horseProfile": {"feeHistory": {"data": [
        {"nominationYear": 2018, "currencyCode": "USD", "studFee": 7500, "countryDesc": "U.S.A", "studName": "Calumet Farm, Kentucky", "isPrivate": False},
        {"nominationYear": 2018, "currencyCode": "USD", "studFee": 7500, "countryDesc": "U.S.A", "studName": "Calumet Farm, Kentucky", "isPrivate": False},
        {"nominationYear": 2019, "currencyCode": "USD", "studFee": 0, "countryDesc": "U.S.A", "studName": "Calumet Farm, Kentucky", "isPrivate": True},
    ]}}}}}}
    rows = rp.fee_rows(payload)
    assert len(rows) == 2
    assert rp.format_fee(rows[0]) == "$7,500"
    assert rp.format_fee(rows[1]) == "Private"


def test_additions_keep_existing_years_and_prefer_usa():
    rows = [
        {"year": 2018, "stud_fee": 7500, "currency": "USD", "is_private": False, "country": "U.S.A", "standing": "Calumet Farm, Kentucky"},
        {"year": 2019, "stud_fee": 20000, "currency": "AUD", "is_private": False, "country": "Australia", "standing": "Arrowfield"},
        {"year": 2019, "stud_fee": 10000, "currency": "USD", "is_private": False, "country": "U.S.A", "standing": "Ashford"},
    ]
    sire = {"name": "Smarty Jones", "key": "SMARTY JONES"}
    out = rp.stud_fee_additions(sire, "598553", rows, have_years={2018})
    assert [(a["Year"], a["Stud Fee"], a["Farm"]) for a in out] == [("2019", "$10,000", "Ashford")]
    assert out[0]["Source List"] == rp.SOURCE
    assert "U.S.A" in out[0]["Notes"]


def test_yob_window():
    assert rp.yob_window(2005, 2020) == (1990, 2002)
    assert rp.yob_window(None, 2020) is None
