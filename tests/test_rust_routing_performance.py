"""S6.8 acceptance arithmetic must remain testable without installing Rust."""

import pytest

from feynmap.rust_routing_performance import evaluate_acceptance


def test_native_acceptance_uses_median_full_route_and_charges_setup():
    result = evaluate_acceptance(
        (10000000, 11000000, 9000000, 10000000, 10000000),
        (3000000, 3100000, 2900000, 3000000, 3000000),
        route_calls_per_sample=100,
        extra_native_setup_ns=7000000,
    )
    assert result["status"] == "pass"
    assert result["end_to_end_route_speedup"] == pytest.approx(10.0 / 3.0)
    assert result["python_mean_route_us"] == 100.0
    assert result["native_mean_route_us"] == 30.0
    assert result["net_saved_us_per_reused_call"] == 70.0
    assert result["break_even_route_calls"] == 100
    assert result["first_route_with_setup_faster"] is False


def test_fast_rust_kernel_is_not_enough_if_complete_native_path_is_slower():
    result = evaluate_acceptance(
        (10000000,) * 5,
        (6000000,) * 5,
        route_calls_per_sample=100,
        extra_native_setup_ns=1000000,
    )
    assert result["status"] == "fail"
    assert result["route_speed_gate_pass"] is False
    assert result["break_even_route_calls"] == 25


def test_native_setup_never_disappears_from_break_even_accounting():
    result = evaluate_acceptance(
        (10000000,) * 5,
        (2000000,) * 5,
        route_calls_per_sample=100,
        extra_native_setup_ns=160000,
    )
    assert result["status"] == "pass"
    assert result["break_even_route_calls"] == 2
    assert result["first_route_with_setup_faster"] is False


def test_no_saving_means_no_break_even():
    result = evaluate_acceptance(
        (10000000,) * 5,
        (11000000,) * 5,
        route_calls_per_sample=100,
        extra_native_setup_ns=1000000,
    )
    assert result["status"] == "fail"
    assert result["break_even_route_calls"] is None
    assert result["net_saved_us_per_reused_call"] < 0


@pytest.mark.parametrize(
    "python,native,calls,extra",
    [
        ((), (), 100, 0),
        ((1, 2), (1,), 100, 0),
        ((0,), (1,), 100, 0),
        ((1,), (0,), 100, 0),
        ((1,), (1,), 0, 0),
        ((1,), (1,), 1, -1),
    ],
)
def test_invalid_performance_samples_are_rejected(python, native, calls, extra):
    with pytest.raises(ValueError):
        evaluate_acceptance(
            python, native,
            route_calls_per_sample=calls,
            extra_native_setup_ns=extra,
        )
