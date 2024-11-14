from genplis.tags import get_tag_size, get_tags


def test_get_tags_mp3(file_mp3):
    tags = get_tags(file_mp3)
    assert tags == {
        "artist": ["Test Artist"],
        "bitrate": 127.488,
        "channels": 2,
        "duration": 3.2653061224489797,
        "encoder_settings": ["Lavf57.83.100"],
        "filename": "/home/fidel/Code/genplis/tests/files/test.mp3",
        "filesize": 53235,
        "genre": ["Synthwave; Retrowave; Electronic"],
        "images": {},
        "samplerate": 44100,
        "title": ["Test"],
    }


def test_get_tags_ogg(file_ogg):
    tags = get_tags(file_ogg)
    assert tags == {
        "artist": ["Test Artist"],
        "bitrate": 112.0,
        "channels": 2,
        "duration": 1.0,
        "encoder": [
            "Lavc58.35.100 libvorbis",
        ],
        "filename": str(file_ogg),
        "filesize": 5241,
        "genre": ["Synthwave", "Retrowave", "Electronic"],
        "images": {},
        "samplerate": 44100,
        "title": ["Test"],
    }


def test_get_tag_size():
    assert get_tag_size(None) == 16
    assert get_tag_size(2) == 28
    assert get_tag_size(128.0) == 24
    assert get_tag_size("") == 41
    assert get_tag_size("DANCE WITH THE DEAD") == 60
    assert get_tag_size(["Synthwave", "Retrowave", "Electronic"]) == 151
