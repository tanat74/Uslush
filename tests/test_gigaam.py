import httpx
import pytest

from bot.gigaam import GigaAMClient


@pytest.mark.asyncio
@pytest.mark.parametrize("media,filename", [("voice", "voice.ogg"), ("video_note", "video.mp4"),
                                           ("video", "video.mp4"), ("m4a", "audio.m4a"),
                                           ("attachment", "media")])
@pytest.mark.parametrize("ending", ["final", "error", "eof", "marker"])
async def test_multipart_stream(monkeypatch, media, filename, ending):
    endings = {
        "final": 'data: {"type":"transcript.text.done","text":"Готово!"}\n\ndata: [DONE]\n\n',
        "error": 'data: {"error":{"message":"failed"}}\n\ndata: [DONE]\n\n',
        "eof": "",
        "marker": "data: [DONE]\n\n",
    }

    async def serve(req):
        assert req.method == "POST" and req.url.path == "/v1/audio/transcriptions"
        assert req.headers["authorization"] == "Bearer secret"
        body = (await req.aread()).decode()
        assert f'filename="{filename}"' in body
        if media == "m4a":
            assert "Content-Type: audio/mp4" in body
        assert "audio-bytes" in body
        for key, value in {"model": "test-model", "stream": "true", "response_format": "json"}.items():
            assert f'name="{key}"\r\n\r\n{value}\r\n' in body
        return httpx.Response(200, text='data: {"type":"transcript.text.delta","delta":" слово"}\n\n' + endings[ending])

    http = httpx.AsyncClient(transport=httpx.MockTransport(serve))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: http)
    client = GigaAMClient("http://server/", "test-model", "secret", 30)
    deltas = []
    run = client.transcribe(b"audio-bytes", media, deltas.append)
    if ending == "final":
        assert await run == "Готово!"
    else:
        with pytest.raises(RuntimeError):
            await run
    assert deltas == [" слово"]
