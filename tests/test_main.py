"""Tests for the main module."""

from real_time_translation.main import main


def test_main(capsys) -> None:
    """Test main function output."""
    main()
    captured = capsys.readouterr()
    assert "Hello from real-time-translation!" in captured.out
