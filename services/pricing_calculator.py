from collections.abc import Iterable, Mapping

from models import Service
from models._validation import validate_nonempty_text, validate_nonnegative_number


class PricingCalculator:
    """Calculates a service total from its configured price options."""

    def calculate_price(
        self,
        service: Service,
        nail_length: str,
        design_add_ons: Iterable[str],
        extras: Mapping[str, int | float] | None = None,
    ) -> float:
        if not isinstance(service, Service):
            raise TypeError("service must be a Service")
        if not isinstance(nail_length, str):
            raise TypeError("nail_length must be a string")

        length_prices = service.length_prices
        if length_prices and nail_length not in length_prices:
            raise ValueError(
                f"Nail length {nail_length!r} is not configured for {service.name}"
            )
        if not length_prices and nail_length:
            raise ValueError(
                f"Nail lengths are not configured for {service.name}"
            )

        add_on_prices = service.design_add_on_prices
        selected_extras = extras if extras is not None else {}
        if not isinstance(selected_extras, Mapping):
            raise TypeError("extras must be a mapping of names to prices")
        normalized_extra_names: set[str] = set()
        for name, price in selected_extras.items():
            validate_nonempty_text(name, "extra name")
            validate_nonnegative_number(price, f"extras[{name!r}]")
            normalized_extra_names.add(name.casefold())
        total = service.base_price + length_prices.get(nail_length, 0)
        included_add_ons: set[str] = set()
        for add_on in design_add_ons:
            if add_on not in add_on_prices:
                raise ValueError(
                    f"Design add-on {add_on!r} is not configured for {service.name}"
                )
            normalized_add_on = add_on.casefold()
            if (
                normalized_add_on not in normalized_extra_names
                and normalized_add_on not in included_add_ons
            ):
                total += add_on_prices[add_on]
            included_add_ons.add(normalized_add_on)
        total += sum(selected_extras.values())
        return total
