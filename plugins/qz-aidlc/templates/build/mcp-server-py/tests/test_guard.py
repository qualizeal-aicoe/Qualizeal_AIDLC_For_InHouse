"""Gates 2 and 5: card and ID numbers never leave the server, and a looping client is stopped."""
from server import guard, policy


def test_card_and_id_numbers_are_masked_in_every_string_of_a_result():
    out = guard.mask({"data": {"note": "card 4111 1111 1111 1111, ID 123-45-6789, ref 1234 5678 9012 3456", "total": 12.5}, "untrusted": ["note"]})
    assert out["data"]["note"] == "card [card number removed], ID [ID number removed], ref 1234 5678 9012 3456"
    assert out["data"]["total"] == 12.5 and out["untrusted"] == ["note"]


def test_a_looping_client_is_stopped_at_the_per_minute_limit(monkeypatch):
    monkeypatch.setattr(policy, "CALLS_PER_MINUTE", 3)
    guard._calls.clear()
    assert [guard.allow_call(now=100.0 + i) for i in range(4)] == [True, True, True, False]
    assert guard.allow_call(now=170.0)                       # a minute later it may call again
    guard._calls.clear()
