from app.services.outfit import OutfitInput, build_outfit_advice


def test_outfit_changes_with_exposure_and_activity():
    short_run = build_outfit_advice(
        OutfitInput(t=4, ws=4, gust=6, r=70, tp=0.0, pmean=0.0, minutes_outside=10, activity="running")
    )
    long_stand = build_outfit_advice(
        OutfitInput(t=4, ws=4, gust=6, r=70, tp=0.0, pmean=0.0, minutes_outside=60, activity="standing")
    )
    assert short_run["base_layer"] != long_stand["base_layer"]
