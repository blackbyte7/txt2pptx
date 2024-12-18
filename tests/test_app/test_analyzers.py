import pytest

from app.analyzers import ContentAnalyzer


@pytest.fixture
def analyzer():
    """ Default ContentAnalyzer instance. """
    return ContentAnalyzer()


@pytest.fixture
def analyzer_strict():
    """ Analyzer with stricter limits. """
    return ContentAnalyzer(max_bullets=3, optimal_words=5, max_title_words=4)


@pytest.fixture
def sample_good_json():
    return {
        "slides": [
            {"slide_number": 1, "slide_type": "opening", "title": "Good Title",
             "bullet_points": ["Point one", "Point two"]},
            {"slide_number": 2, "slide_type": "content", "title": "Another Title",
             "bullet_points": ["Data A", "Data B", "Data C"], "speaker_notes": "Note here."}
        ]
    }


@pytest.fixture
def sample_bad_json_format():
    return {"no_slides_key": []}


@pytest.fixture
def sample_json_too_many_bullets():
    return {
        "slides": [
            {"slide_number": 1, "title": "Too Much Info", "bullet_points": ["1", "2", "3", "4", "5", "6", "7", "8"]}
        ]
    }


@pytest.fixture
def sample_json_long_bullets():
    return {
        "slides": [
            {"slide_number": 1, "title": "Wordy",
             "bullet_points": ["This is a very long bullet point that exceeds the optimal word count significantly."]}
        ]
    }


@pytest.fixture
def sample_json_long_title():
    return {
        "slides": [
            {"slide_number": 1, "title": "This Title is Definitely Far Too Long For a Presentation Slide",
             "bullet_points": ["Concise point."]}
        ]
    }


@pytest.fixture
def sample_json_missing_title():
    return {
        "slides": [
            {"slide_number": 1, "bullet_points": ["Needs title"]}
        ]
    }


@pytest.fixture
def sample_json_empty_bullets():
    return {
        "slides": [
            {"slide_number": 1, "title": "Empty Points", "bullet_points": ["Point 1", "", "Point 3"]}
        ]
    }


@pytest.fixture
def sample_json_no_bullets_content_slide():
    return {
        "slides": [
            {"slide_number": 1, "title": "No Content Here", "slide_type": "content", "bullet_points": []}
        ]
    }


@pytest.fixture
def sample_json_invalid_types():
    return {
        "slides": [
            {"slide_number": 1, "title": 123, "bullet_points": "not a list", "speaker_notes": ["not a string"]}
        ]
    }


def test_init_defaults(analyzer):
    assert analyzer.max_bullets_per_slide == 7
    assert analyzer.optimal_words_per_bullet == 20
    assert analyzer.max_title_words == 10


def test_init_custom(analyzer_strict):
    assert analyzer_strict.max_bullets_per_slide == 3
    assert analyzer_strict.optimal_words_per_bullet == 5
    assert analyzer_strict.max_title_words == 4


def test_analyze_good_structure(analyzer, sample_good_json):
    analysis = analyzer.analyze_presentation_structure(sample_good_json)
    assert not analysis["warnings"]


def test_analyze_invalid_format(analyzer, sample_bad_json_format):
    analysis = analyzer.analyze_presentation_structure(sample_bad_json_format)
    assert len(analysis["warnings"]) == 1
    assert "Invalid presentation structure format" in analysis["warnings"][0]
    assert not analysis["suggestions"]


def test_analyze_no_slides(analyzer):
    analysis = analyzer.analyze_presentation_structure({"slides": []})
    assert len(analysis["warnings"]) == 1
    assert "Presentation structure has no slides" in analysis["warnings"][0]
    assert not analysis["suggestions"]


def test_analyze_single_slide(analyzer):
    analysis = analyzer.analyze_presentation_structure({"slides": [{"title": "Single"}]})
    assert not analysis["warnings"]
    assert len(analysis["suggestions"]) >= 1
    assert "Consider adding more slides" in analysis["suggestions"][0]


def test_analyze_too_many_slides(analyzer):
    many_slides = {"slides": [{"title": f"S{i}"} for i in range(25)]}
    analysis = analyzer.analyze_presentation_structure(many_slides)
    assert len(analysis["warnings"]) == 1
    assert "large number of slides (25)" in analysis["warnings"][0]


def test_analyze_too_many_bullets(analyzer, sample_json_too_many_bullets):
    analysis = analyzer.analyze_presentation_structure(sample_json_too_many_bullets)
    assert len(analysis["warnings"]) == 1
    assert "Contains 8 bullet points (>7)" in analysis["warnings"][0]


def test_analyze_too_many_bullets_strict(analyzer_strict, sample_json_too_many_bullets):
    analysis = analyzer_strict.analyze_presentation_structure(sample_json_too_many_bullets)
    assert len(analysis["warnings"]) == 1
    assert "Contains 8 bullet points (>3)" in analysis["warnings"][0]


def test_analyze_long_bullets(analyzer, sample_json_long_bullets):
    analysis = analyzer.analyze_presentation_structure(sample_json_long_bullets)
    assert not analysis["warnings"]
    assert len(analysis["suggestions"]) >= 1
    long_bullet_suggestion_part = "Is long (14 words > 20)"
    assert not any(long_bullet_suggestion_part in s for s in analysis["suggestions"]), \
        f"Unexpected long bullet suggestion found: {analysis['suggestions']}"
    single_slide_suggestion_part = "Consider adding more slides"
    assert any(single_slide_suggestion_part in s for s in analysis["suggestions"]), \
        f"Expected single-slide suggestion not found in {analysis['suggestions']}"


def test_analyze_long_bullets_strict(analyzer_strict, sample_json_long_bullets):
    analysis = analyzer_strict.analyze_presentation_structure(sample_json_long_bullets)
    assert not analysis["warnings"]
    assert len(analysis["suggestions"]) >= 1
    expected_suggestion_part = "Is long (14 words > 5)"
    assert any(expected_suggestion_part in s for s in analysis["suggestions"]), \
         f"Expected suggestion containing '{expected_suggestion_part}' not found in {analysis['suggestions']}"


def test_analyze_long_title(analyzer, sample_json_long_title):
    analysis = analyzer.analyze_presentation_structure(sample_json_long_title)
    assert not analysis["warnings"]
    assert len(analysis["suggestions"]) >= 1
    expected_suggestion_part = "Title is long (11 words > 10)"
    assert any(expected_suggestion_part in s for s in analysis["suggestions"]), \
         f"Expected suggestion containing '{expected_suggestion_part}' not found in {analysis['suggestions']}"


def test_analyze_long_title_strict(analyzer_strict, sample_json_long_title):
    analysis = analyzer_strict.analyze_presentation_structure(sample_json_long_title)
    assert not analysis["warnings"]
    assert len(analysis["suggestions"]) >= 1
    expected_suggestion_part = "Title is long (11 words > 4)"
    assert any(expected_suggestion_part in s for s in analysis["suggestions"]), \
         f"Expected suggestion containing '{expected_suggestion_part}' not found in {analysis['suggestions']}"


def test_analyze_missing_title(analyzer, sample_json_missing_title):
    analysis = analyzer.analyze_presentation_structure(sample_json_missing_title)
    assert len(analysis["warnings"]) == 1
    assert "Is missing a title" in analysis["warnings"][0]


def test_analyze_empty_bullets(analyzer, sample_json_empty_bullets):
    analysis = analyzer.analyze_presentation_structure(sample_json_empty_bullets)
    assert len(analysis["warnings"]) == 1
    assert "Bullet 2: Is empty" in analysis["warnings"][0]


def test_analyze_no_bullets_on_content_slide(analyzer, sample_json_no_bullets_content_slide):
    analysis = analyzer.analyze_presentation_structure(sample_json_no_bullets_content_slide)
    assert not analysis["warnings"]
    assert len(analysis["suggestions"]) >= 1
    expected_suggestion_part = "Has no bullet points"
    assert any(expected_suggestion_part in s for s in analysis["suggestions"]), \
         f"Expected suggestion containing '{expected_suggestion_part}' not found in {analysis['suggestions']}"


def test_analyze_invalid_types(analyzer, sample_json_invalid_types):
    analysis = analyzer.analyze_presentation_structure(sample_json_invalid_types)
    assert len(analysis["warnings"]) == 4
    assert "Invalid format for 'title'. Expected a string" in analysis["warnings"][0] or \
           "Invalid format for 'title'. Expected a string" in analysis["warnings"][1] or \
           "Invalid format for 'title'. Expected a string" in analysis["warnings"][2] or \
           "Invalid format for 'title'. Expected a string" in analysis["warnings"][3]

    assert "Invalid format for 'bullet_points'. Expected a list" in analysis["warnings"][0] or \
           "Invalid format for 'bullet_points'. Expected a list" in analysis["warnings"][1] or \
           "Invalid format for 'bullet_points'. Expected a list" in analysis["warnings"][2] or \
           "Invalid format for 'bullet_points'. Expected a list" in analysis["warnings"][3]

    assert "Invalid format for 'speaker_notes'. Expected a string" in analysis["warnings"][0] or \
           "Invalid format for 'speaker_notes'. Expected a string" in analysis["warnings"][1] or \
           "Invalid format for 'speaker_notes'. Expected a string" in analysis["warnings"][2] or \
           "Invalid format for 'speaker_notes'. Expected a string" in analysis["warnings"][3]

    assert "Is missing a title. Most slides benefit from a clear title." in analysis["warnings"][0] or \
           "Is missing a title. Most slides benefit from a clear title." in analysis["warnings"][1] or \
           "Is missing a title. Most slides benefit from a clear title." in analysis["warnings"][2] or \
           "Is missing a title. Most slides benefit from a clear title." in analysis["warnings"][3]
