"""SMTP transport against a local fake server + recipient/compose unit tests."""

from __future__ import annotations

import pytest

from app.mailer import (
    RecipientSet,
    SmtpConfig,
    SmtpError,
    invalid_addresses,
    normalize_recipients,
    send_message,
    test_connection as smtp_test_connection,
    valid_email,
)
from app.smtp_store import delivery_key, mask_email

from .fake_smtp import FakeSMTP


def _cfg(server: FakeSMTP, **kw) -> SmtpConfig:
    base = dict(
        host="127.0.0.1", port=server.port, security_mode="plain",
        auth_enabled=False, sender_email="from@example.com", timeout=5,
    )
    base.update(kw)
    return SmtpConfig(**base)


def _msg():
    from email.message import EmailMessage

    m = EmailMessage()
    m["Subject"] = "Test"
    m["From"] = "from@example.com"
    m["To"] = "a@example.com"
    m.set_content("hello")
    return m


# -- recipients ------------------------------------------------------------- #


def test_valid_email_and_header_injection():
    assert valid_email("a@b.com")
    assert not valid_email("not-an-email")
    assert not valid_email("a@b.com\r\nBcc: evil@x.com")  # CRLF injection blocked
    assert not valid_email("a@b.com\nX-Inject: y")


def test_recipient_dedup_across_buckets_case_insensitive():
    r = normalize_recipients(["A@x.com", "a@x.com"], ["A@X.com"], ["b@x.com", "B@x.com"])
    assert r.to == ["A@x.com"]
    assert r.cc == []  # already in To
    assert r.bcc == ["b@x.com"]
    assert r.count == 2


def test_invalid_addresses_detected():
    assert invalid_addresses(["good@x.com", "bad", "x@y.com\r\nevil"]) == ["bad", "x@y.com\r\nevil"]


def test_mask_email():
    assert mask_email("alice@example.com") == "a***@e***.com"


def test_delivery_key_is_stable_and_order_independent():
    r1 = RecipientSet(to=["a@x.com", "b@x.com"])
    r2 = RecipientSet(to=["b@x.com", "a@x.com"])
    k1 = delivery_key(schedule_id=1, report_uuid="u", rcpts=r1, formats=["pdf"])
    k2 = delivery_key(schedule_id=1, report_uuid="u", rcpts=r2, formats=["pdf"])
    k3 = delivery_key(schedule_id=1, report_uuid="u", rcpts=r1, formats=["pdf", "csv"])
    assert k1 == k2
    assert k1 != k3  # different attachment set -> different delivery


# -- transport against the fake server -------------------------------------- #


def test_connection_ok():
    srv = FakeSMTP("ok")
    try:
        smtp_test_connection(_cfg(srv))  # no exception
    finally:
        srv.stop()


def test_send_message_delivers_and_records():
    srv = FakeSMTP("ok")
    try:
        outcome = send_message(_cfg(srv), _msg(), RecipientSet(to=["a@example.com"]))
        assert outcome == {"a@example.com": "accepted"}
        assert len(srv.messages) == 1
    finally:
        srv.stop()


def test_send_partial_recipient_rejection():
    srv = FakeSMTP("reject_one", reject=["bad@example.com"])
    try:
        outcome = send_message(
            _cfg(srv), _msg(), RecipientSet(to=["good@example.com", "bad@example.com"])
        )
        assert outcome["good@example.com"] == "accepted"
        assert outcome["bad@example.com"] == "rejected"
    finally:
        srv.stop()


def test_send_all_recipients_rejected():
    srv = FakeSMTP("reject_all")
    try:
        outcome = send_message(_cfg(srv), _msg(), RecipientSet(to=["x@example.com"]))
        assert outcome["x@example.com"] == "rejected"
    finally:
        srv.stop()


def test_temporary_failure_classified():
    srv = FakeSMTP("temp")
    try:
        with pytest.raises(SmtpError) as ei:
            send_message(_cfg(srv), _msg(), RecipientSet(to=["x@example.com"]))
        assert ei.value.category == "temporary_smtp"
    finally:
        srv.stop()


def test_permanent_failure_classified():
    srv = FakeSMTP("perm")
    try:
        with pytest.raises(SmtpError) as ei:
            send_message(_cfg(srv), _msg(), RecipientSet(to=["x@example.com"]))
        assert ei.value.category == "permanent_smtp"
    finally:
        srv.stop()


def test_authentication_failure_classified():
    srv = FakeSMTP("authfail")
    try:
        cfg = _cfg(srv, auth_enabled=True, username="u", password="p", allow_insecure_plain=True)
        with pytest.raises(SmtpError) as ei:
            smtp_test_connection(cfg)
        assert ei.value.category == "authentication"
    finally:
        srv.stop()


def test_plain_auth_refused_without_explicit_optin():
    srv = FakeSMTP("ok")
    try:
        cfg = _cfg(srv, auth_enabled=True, username="u", password="p", allow_insecure_plain=False)
        with pytest.raises(SmtpError) as ei:
            smtp_test_connection(cfg)
        assert ei.value.category == "tls"  # refuses credentials over plaintext
    finally:
        srv.stop()


def test_secret_never_appears_in_error_messages():
    srv = FakeSMTP("authfail")
    try:
        cfg = _cfg(srv, auth_enabled=True, username="u", password="SUPERSECRET", allow_insecure_plain=True)
        with pytest.raises(SmtpError) as ei:
            smtp_test_connection(cfg)
        assert "SUPERSECRET" not in str(ei.value)
    finally:
        srv.stop()
