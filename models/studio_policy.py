class StudioPolicy:
    """Read-only policy values shared by appointment and client workflows."""

    __DEPOSIT_AMOUNT = 100
    __CANCELLATION_FEE = 50
    __NOTICE_HOURS = 48
    __MIN_MINUTES = 5
    __MAX_MINUTES = 240

    @property
    def deposit_amount(self) -> int:
        return self.__DEPOSIT_AMOUNT

    @property
    def cancellation_fee(self) -> int:
        return self.__CANCELLATION_FEE

    @property
    def notice_hours(self) -> int:
        return self.__NOTICE_HOURS

    @property
    def min_minutes(self) -> int:
        return self.__MIN_MINUTES

    @property
    def max_minutes(self) -> int:
        return self.__MAX_MINUTES
