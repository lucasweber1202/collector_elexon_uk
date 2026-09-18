from datetime import date

from scripts.extract_elexon_mid import _build_catalog


def test_settlement_date_is_not_publication_date():
    fields = {
        "ELEXON_MID_APXMIDP_VOLUME_SP01": {
            "measure": "VOLUME",
            "provider": "APXMIDP",
            "settlement_period": "1",
        }
    }
    row = _build_catalog(fields, date(2026, 9, 18))["ELEXON_MID_APXMIDP_VOLUME_SP01"]
    assert row["last_publish_date"] is None
    assert row["unit"] == "megawatt_hours"
