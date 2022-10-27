class TestPlugin:
    """Offline tests"""

    def test_bridge(self, mocker) -> None:
        msg = mocker.get_one_reply("/bridge -1234")
        assert "❌" in msg.text

    def test_unbridge(self, mocker) -> None:
        msg = mocker.get_one_reply("/unbridge")
        assert "❌" in msg.text
