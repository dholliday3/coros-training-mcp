import traininghub_static_enums as extractor


def test_parse_simple_object_quotes_bare_keys_and_numeric_keys():
    script = 'targetTypeName={0:"notSet",1:"manualEnd",2:"time"}'

    parsed = extractor.parse_simple_object(script, "targetTypeName=")

    assert parsed == {0: "notSet", 1: "manualEnd", 2: "time"}


def test_parse_sport_category_extracts_i18n_and_exercise_types():
    script = (
        'sportCategory={run:{i18n:"H2005",sportIcon:getImageAssetsFile("sport/Running.svg"),'
        'exerciseTypes:["warmup","train","relax"],sportType:"icon-outrun"},'
        'strength:{i18n:"H2008",sportIcon:getImageAssetsFile("sport/Strength.svg"),'
        'exerciseTypes:["warmup","train","relax","rest"],sportType:"icon-strength"}}'
    )

    parsed = extractor.parse_sport_category(script)

    assert parsed["run"]["i18n_key"] == "H2005"
    assert parsed["run"]["exercise_types"] == ["warmup", "train", "relax"]
    assert parsed["strength"]["icon_name"] == "icon-strength"


def test_build_registry_resolves_display_values():
    assets = extractor.TrainingHubAssets(
        index_url="https://training.coros.com/",
        locale_url="https://static.coros.com/locale/coros-traininghub-v2/en-US.prod.js",
        main_url="https://static.coros.com/coros-traininghub-v2/public/main.js",
        locale_text=(
            '"H2005": "Run", '
            '"R6008": "Not Set", '
            '"T1120": "Warm Up", '
            '"T1121": "Training", '
            '"T1122": "Cool Down", '
            '"T1123": "Rest"'
        ),
        main_text=(
            'sportCategory={run:{i18n:"H2005",exerciseTypes:["warmup","train","relax"],sportType:"icon-outrun"}},'
            'targetTypeName={0:"notSet",2:"time"},'
            'targetType={notSet:{i18n:"R6008"},time:{i18n:"时间"}},'
            'intensityTypeName={0:"notSet",8:"adjustedPace"},'
            'intensityUnitName={1:"min/km"},'
            'restTypeName={0:"manualEnd",1:"time"},'
            'restType={manualEnd:{i18n:"手动结束"},time:{i18n:"时间"}},'
            'exerciseTypeName={1:"warmup",2:"train",3:"relax",4:"rest"},'
            'exerciseTypeOptions={warmup:{i18n:"T1120",color:"#FFA400"},train:{i18n:"T1121",color:"#20CD61"},'
            'relax:{i18n:"T1122",color:"#00D5FF"},rest:{i18n:"T1123",color:"#9A9A9A"}},'
            'sportTypeName={100:"Run",402:"Strength"}'
        ),
    )

    registry = extractor.build_registry(assets)

    assert registry["enums"]["target_type"][0]["display"] == "Not Set"
    assert registry["enums"]["target_type"][1]["display"] == "Time"
    assert registry["enums"]["intensity_type"][1]["display"] == "Effort Pace"
    assert registry["enums"]["exercise_type"][0]["display"] == "Warm Up"
    assert registry["enums"]["sport_category"][0]["display"] == "Run"
