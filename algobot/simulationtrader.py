from datetime import datetime
from helpers import get_logger
from data import Data
from enums import LONG, SHORT, BEARISH, BULLISH, TRAILING_LOSS, STOP_LOSS


class SimulationTrader:
    def __init__(self, startingBalance: float = 1000, interval: str = '1h', symbol: str = 'BTCUSDT',
                 loadData: bool = True, updateData: bool = True, logFile: str = 'simulation'):
        """
        SimulationTrader object that will mimic real live market trades.
        :param startingBalance: Balance to start simulation trader with.
        :param interval: Interval to start trading on.
        :param symbol: Symbol to start trading with.
        :param loadData: Boolean whether we load data from data object or not.
        :param updateData: Boolean for whether data will be updated if it is loaded.
        :param logFile: Filename that logger will log to.
        """
        self.logger = get_logger(logFile=logFile, loggerName=logFile)  # Get logger.
        self.dataView: Data = Data(interval=interval, symbol=symbol, loadData=loadData,
                                   updateData=updateData, logObject=self.logger)
        self.binanceClient = self.dataView.binanceClient  # Retrieve Binance client.
        self.symbol = self.dataView.symbol  # Retrieve symbol from data-view object.

        # Initialize initial values.
        self.balance = startingBalance  # USDT Balance.
        self.startingBalance = self.balance  # Balance we started bot run with.
        self.previousNet = self.balance
        self.coinName = self.get_coin_name()  # Retrieve primary coin to trade.
        self.coin = 0  # Amount of coin we own.
        self.coinOwed = 0  # Amount of coin we owe.
        self.transactionFeePercentage = 0.001  # Binance transaction fee percentage.
        self.trades = []  # All trades performed.
        self.commissionPaid = 0  # Total commission paid to broker.
        self.dailyChangeNets = []  # Daily change net list. Will contain list of all nets.

        self.completedLoop = True  # Loop that'll keep track of bot. We wait for this to turn False before some action.

        self.tradingOptions = []  # List with Option elements. Helps specify what moving averages to trade with.
        self.optionDetails = []  # Current option values. Holds most recent option values.
        self.lowerOptionDetails = []  # Lower option values. Holds lower interval option values (if exist).
        self.trend = None  # 1 is bullish, -1 is bearish; usually handled with enums.
        self.lossPercentageDecimal = None  # Loss percentage in decimal for stop loss.
        self.startingTime = datetime.utcnow()  # Starting time in UTC.
        self.endingTime = None  # Ending time for previous bot run.

        self.buyLongPrice = None  # Price we last bought our target coin at in long position.
        self.sellShortPrice = None  # Price we last sold target coin at in short position.
        self.lossStrategy = None  # Type of loss type we are using: whether it's trailing loss or stop loss.
        self.customStopLoss = None  # Custom stop loss to use if we want to exit trade before trailing or stop loss.
        self.stopLoss = None  # Price at which bot will exit trade due to stop loss limits.
        self.longTrailingPrice = None  # Price coin has to be above for long position.
        self.shortTrailingPrice = None  # Price coin has to be below for short position.
        self.currentPrice = None  # Current price of coin.

        self.inHumanControl = False  # Boolean that keeps track of whether human or bot controls transactions.
        self.currentPosition = None  # Current position value.
        self.previousPosition = None  # Previous position to validate for a cross.
        self.stoicTrend = None  # Current stoic trend is enabled.
        self.stoicEnabled = False  # Boolean that holds whether stoic trading is enabled or not.
        self.stoicOptions = [None, None, None]  # Stoic options.
        self.stoicDictionary = {}  # Dictionary for stoic strategies.

    def output_message(self, message: str, level: int = 2, printMessage: bool = False):
        """
        Prints out and logs message provided.
        :param message: Message to be logged and/or outputted.
        :param level: Level to be debugged at.
        :param printMessage: Boolean that determines whether messaged will be printed or not.
        """
        if printMessage:
            print(message)
        if level == 2:
            self.logger.info(message)
        elif level == 3:
            self.logger.debug(message)
        elif level == 4:
            self.logger.warning(message)
        elif level == 5:
            self.logger.critical(message)

    def add_trade(self, message: str, initialNet: float, finalNet: float, price: float, force: bool, orderID=None):
        """
        Adds a trade to list of trades
        :param orderID: Order ID returned from Binance API.
        :param finalNet: Final net balance after trade was conducted.
        :param initialNet: Initial net balance before trade was conducted.
        :param force: Boolean that determines whether trade was conducted autonomously or by hand.
        :param price: Price trade was conducted at.
        :param message: Message used for conducting trade.
        """
        profit = finalNet - initialNet
        profitPercentage = self.get_profit_percentage(initialNet, finalNet)
        method = "Manual" if force else "Automation"

        self.trades.append({
            'date': datetime.utcnow(),
            'orderID': orderID,
            'action': message,
            'pair': self.symbol,
            'price': f'${round(price, 2)}',
            'method': method,
            'percentage': f'{round(profitPercentage, 2)}%',
            'profit': f'${round(profit, 2)}'
        })

        self.output_message(f'\nDatetime in UTC: {datetime.utcnow()}\n'
                            f'Order ID: {orderID}\n'
                            f'Action: {message}\n'
                            f'Pair: {self.symbol}\n'
                            f'Price: {round(price, 2)}\n'
                            f'Method: {method}\n'
                            f'Percentage: {round(profitPercentage, 2)}%\n'
                            f'Profit: ${round(profit, 2)}\n')

    def buy_long(self, msg: str, usd: float = None, force: bool = False):
        """
        Buys coin at current market price with amount of USD specified. If not specified, assumes bot goes all in.
        Function also takes into account Binance's 0.1% transaction fee.
        :param msg: Message to be used for displaying trade information.
        :param usd: Amount used to enter long.
        :param force: Boolean that determines whether bot executed action or human.
        """
        if usd is None:
            usd = self.balance

        if usd <= 0:
            raise ValueError(f"You cannot buy with ${usd}.")
        elif usd > self.balance:
            raise ValueError(f'You currently have ${self.balance}. You cannot invest ${usd}.')

        self.currentPrice = self.dataView.get_current_price()
        transactionFee = usd * self.transactionFeePercentage
        self.commissionPaid += transactionFee
        self.currentPosition = LONG
        self.buyLongPrice = self.longTrailingPrice = self.currentPrice
        self.coin += (usd - transactionFee) / self.currentPrice
        self.balance -= usd
        finalNet = self.get_net()
        self.add_trade(msg, initialNet=self.previousNet, finalNet=finalNet, price=self.currentPrice, force=force)
        self.previousNet = finalNet

    def sell_long(self, msg: str, coin: float = None, force: bool = False):
        """
        Sells specified amount of coin at current market price. If not specified, assumes bot sells all coin.
        Function also takes into account Binance's 0.1% transaction fee.
        :param msg: Message to be used for displaying trade information.
        :param coin: Coin amount to sell to exit long.
        :param force: Boolean that determines whether bot executed action or human.
        """
        if coin is None:
            coin = self.coin

        if coin <= 0:
            raise ValueError(f"You cannot sell {coin} {self.coinName}.")
        elif coin > self.coin:
            raise ValueError(f'You have {self.coin} {self.coinName}. You cannot sell {coin} {self.coinName}.')

        self.currentPrice = self.dataView.get_current_price()
        self.commissionPaid += coin * self.currentPrice * self.transactionFeePercentage
        earned = coin * self.currentPrice * (1 - self.transactionFeePercentage)
        self.currentPosition = None
        self.customStopLoss = None
        self.previousPosition = LONG
        self.coin -= coin
        self.balance += earned
        finalNet = self.get_net()
        self.add_trade(msg, initialNet=self.previousNet, finalNet=finalNet, price=self.currentPrice, force=force)
        self.previousNet = finalNet

        if self.coin == 0:
            self.buyLongPrice = self.longTrailingPrice = None

    def buy_short(self, msg: str, coin: float = None, force: bool = False):
        """
        Buys borrowed coin at current market price and returns to market.
        Function also takes into account Binance's 0.1% transaction fee.
        If coin amount is not specified, bot will assume to try to pay back everything in return.
        :param msg: Message to be used for displaying trade information.
        :param coin: Coin amount to buy back to exit short position.
        :param force: Boolean that determines whether bot executed action or human.
        """
        if coin is None:
            coin = self.coinOwed

        if coin <= 0:
            raise ValueError(f"You cannot buy {coin} {self.coinName}.")

        self.currentPrice = self.dataView.get_current_price()
        self.coinOwed -= coin
        self.customStopLoss = None
        self.currentPosition = None
        self.previousPosition = SHORT
        self.commissionPaid += self.currentPrice * coin * self.transactionFeePercentage
        self.balance -= self.currentPrice * coin * (1 + self.transactionFeePercentage)
        finalNet = self.get_net()
        self.add_trade(msg, initialNet=self.previousNet, finalNet=finalNet, price=self.currentPrice, force=force)
        self.previousNet = finalNet

        if self.coinOwed == 0:
            self.sellShortPrice = None
            self.shortTrailingPrice = None

    def sell_short(self, msg: str, coin: float = None, force: bool = False):
        """
        Borrows coin and sells them at current market price.
        Function also takes into account Binance's 0.1% transaction fee.
        If no coin is provided in function, bot will assume we borrow as much as
        bot can buy with current balance and market value.
        :param msg: Message to be used for displaying trade information.
        :param coin: Coin amount to sell to enter short position.
        :param force: Boolean that determines whether bot executed action or human.
        """
        self.currentPrice = self.dataView.get_current_price()

        if coin is None:
            transactionFee = self.balance * self.transactionFeePercentage
            coin = (self.balance - transactionFee) / self.currentPrice

        if coin <= 0:
            raise ValueError(f"You cannot borrow negative {abs(coin)} {self.coinName}.")

        self.coinOwed += coin
        self.commissionPaid += self.currentPrice * coin * self.transactionFeePercentage
        self.balance += self.currentPrice * coin * (1 - self.transactionFeePercentage)
        self.currentPosition = SHORT
        self.sellShortPrice = self.shortTrailingPrice = self.currentPrice
        finalNet = self.get_net()
        self.add_trade(msg, force=force, initialNet=self.previousNet, finalNet=finalNet, price=self.currentPrice)
        self.previousNet = finalNet

    # noinspection DuplicatedCode
    def stoic_strategy(self, input1: int, input2: int, input3: int, s: int = 0) -> None or int:
        """
        Custom strategy.
        :param input1: Custom input 1 for the stoic strategy.
        :param input2: Custom input 2 for the stoic strategy.
        :param input3: Custom input 3 for the stoic strategy.
        :param s: Shift data to get previous values.
        :return: Bullish, bearish, or none values.
        """
        self.dataView.data.insert(0, self.dataView.get_current_data())
        rsi_values_one = [self.dataView.get_rsi(input1, shift=shift, update=False) for shift in range(s, input1 + s)]
        rsi_values_two = [self.dataView.get_rsi(input2, shift=shift, update=False) for shift in range(s, input2 + s)]
        self.dataView.data = self.dataView.data[1:]

        seneca = max(rsi_values_one) - min(rsi_values_one)
        if 'seneca' in self.stoicDictionary:
            self.stoicDictionary['seneca'].insert(0, seneca)
        else:
            self.stoicDictionary['seneca'] = [seneca]

        zeno = rsi_values_one[0] - min(rsi_values_one)
        if 'zeno' in self.stoicDictionary:
            self.stoicDictionary['zeno'].insert(0, zeno)
        else:
            self.stoicDictionary['zeno'] = [zeno]

        gaius = rsi_values_two[0] - min(rsi_values_two)
        if 'gaius' in self.stoicDictionary:
            self.stoicDictionary['gaius'].insert(0, gaius)
        else:
            self.stoicDictionary['gaius'] = [gaius]

        philo = max(rsi_values_two) - min(rsi_values_two)
        if 'philo' in self.stoicDictionary:
            self.stoicDictionary['philo'].insert(0, philo)
        else:
            self.stoicDictionary['philo'] = [philo]

        if len(self.stoicDictionary['gaius']) < 3:
            return None

        hadot = sum(self.stoicDictionary['gaius'][:3]) / sum(self.stoicDictionary['philo'][:3]) * 100
        if 'hadot' in self.stoicDictionary:
            self.stoicDictionary['hadot'].insert(0, hadot)
        else:
            self.stoicDictionary['hadot'] = [hadot]

        if len(self.stoicDictionary['hadot']) < 3:
            return None

        stoic = sum(self.stoicDictionary['zeno'][:3]) / sum(self.stoicDictionary['seneca'][:3]) * 100
        marcus = sum(self.stoicDictionary['hadot'][:input3]) / input3

        self.output_message(f'Inputs: {input1}, {input2}, {input3}')
        self.output_message(f'\nMarcus: {marcus}')
        self.output_message(f'Stoic: {stoic}\n')

        if marcus > stoic:
            self.stoicTrend = BEARISH
            return BEARISH
        elif marcus < stoic:
            self.stoicTrend = BULLISH
            return BULLISH
        else:
            self.stoicTrend = None
            return None

    # noinspection PyTypeChecker
    def main_logic(self, log_data=True):
        """
        Main bot logic will use to trade.
        If there is a trend and the previous position did not reflect the trend, the bot enters position.
        :param log_data: Boolean that will determine where data is logged or not.
        """
        s1, s2, s3 = self.stoicOptions
        if self.stoicEnabled:
            try:
                self.stoic_strategy(s1, s2, s3)
            except Exception as e:
                raise ValueError(f"Invalid stoic options: {e} occurred.")

        if self.currentPosition == SHORT:  # This means we are in short position
            if self.customStopLoss is not None and self.currentPrice >= self.customStopLoss:
                self.buy_short(f'Bought short because of custom stop loss.')

            elif self.get_stop_loss() is not None and self.currentPrice >= self.get_stop_loss():
                self.buy_short(f'Bought short because of stop loss.')

            elif not self.inHumanControl and self.check_cross(log_data=log_data):
                if self.stoicEnabled:
                    if self.stoicTrend == BULLISH:
                        self.buy_short(f'Bought short because a cross and stoicism were detected.')
                        self.buy_long(f'Bought long because a cross and stoicism were detected.')
                else:
                    self.buy_short(f'Bought short because a cross was detected.')
                    self.buy_long(f'Bought long because a cross was detected.')

        elif self.currentPosition == LONG:  # This means we are in long position
            if self.customStopLoss is not None and self.currentPrice <= self.customStopLoss:
                self.sell_long(f'Sold long because of custom stop loss.')

            elif self.get_stop_loss() is not None and self.currentPrice <= self.get_stop_loss():
                self.sell_long(f'Sold long because of stop loss.')

            elif not self.inHumanControl and self.check_cross(log_data=log_data):
                if self.stoicEnabled:
                    if self.stoicTrend == BEARISH:
                        self.sell_long(f'Sold long because a cross and stoicism were detected.')
                        self.sell_short('Sold short because a cross and stoicism were detected.')
                else:
                    self.sell_long(f'Sold long because a cross was detected.')
                    self.sell_short('Sold short because a cross was detected.')

        else:  # This means we are in neither position
            if not self.inHumanControl and self.check_cross(log_data=log_data):
                if self.trend == BULLISH:  # This checks if we are bullish or bearish
                    if self.stoicEnabled:
                        if self.stoicTrend == BULLISH:
                            self.buy_long("Bought long because a cross and stoicism were detected.")
                    else:
                        self.buy_long("Bought long because a cross was detected.")
                elif self.trend == BEARISH:
                    if self.stoicEnabled:
                        if self.stoicTrend == BEARISH:
                            self.sell_short("Sold short because a cross and stoicism were detected.")
                    else:
                        self.sell_short("Sold short because a cross was detected.")

    def get_stop_loss_strategy_string(self) -> str:
        """
        Returns stop loss strategy in string format, instead of integer enum.
        :return: Stop loss strategy in string format.
        """
        if self.lossStrategy == STOP_LOSS:
            return 'Stop Loss'
        elif self.lossStrategy == TRAILING_LOSS:
            return 'Trailing Loss'
        elif self.lossStrategy is None:
            return 'None'
        else:
            raise ValueError("Unknown type of loss strategy.")

    @staticmethod
    def get_trend_string(trend) -> str:
        if trend == BULLISH:
            return "Bullish"
        elif trend == BEARISH:
            return 'Bearish'
        elif trend is None:
            return 'None'
        else:
            raise ValueError("Unknown type of trend.")

    def get_position_string(self) -> str:
        """
        Returns position in string format, instead of integer enum.
        :return: Position in string format.
        """
        if self.currentPosition == LONG:
            return 'Long'
        elif self.currentPosition == SHORT:
            return 'Short'
        elif self.currentPosition is None:
            return 'None'
        else:
            raise ValueError("Invalid type of current position.")

    @staticmethod
    def get_safe_rounded_string(value: float, roundDigits: int = 2, symbol: str = '$') -> str:
        """
        Helper function that will, if exists, return value rounded with symbol provided.
        :param roundDigits: Number of digits to round value.
        :param symbol: Symbol to insert to beginning of return string.
        :param value: Value that will be safety checked.
        :return: Rounded value (if not none) in string format.
        """
        if value is None:
            return "None"
        else:
            return f'{symbol}{round(value, roundDigits)}'

    @staticmethod
    def get_profit_or_loss_string(profit: float) -> str:
        """
        Helper function that returns where profit specified is profit or loss. Profit is positive; loss if negative.
        :param profit: Amount to be checked for negativity or positivity.
        :return: String value of whether profit ir positive or negative.
        """
        return "Profit" if profit >= 0 else "Loss"

    def get_stoic_inputs(self):
        if not self.stoicEnabled:
            return 'None'
        return f'{self.stoicOptions[0]}, {self.stoicOptions[1]}, {self.stoicOptions[2]}'

    def get_net(self) -> float:
        """
        Returns net balance with current price of coin being traded. It factors in the current balance, the amount
        shorted, and the amount owned.
        :return: Net balance.
        """
        if self.currentPrice is None:
            self.currentPrice = self.dataView.get_current_price()

        return self.startingBalance + self.get_profit()

    def get_profit(self) -> float:
        """
        Returns profit or loss.
        :return: A number representing profit if positive and loss if negative.
        """
        if self.currentPrice is None:
            self.currentPrice = self.dataView.get_current_price()

        balance = self.balance
        balance += self.currentPrice * self.coin
        balance -= self.currentPrice * self.coinOwed

        return balance - self.startingBalance

    @staticmethod
    def get_profit_percentage(initialNet: float, finalNet: float) -> float:
        """
        Calculates net percentage from initial and final values and returns it.
        :param initialNet: Initial net value.
        :param finalNet: Final net value.
        :return: Profit percentage.
        """
        if finalNet > initialNet:
            return finalNet / initialNet * 100 - 100
        else:
            return -1 * (100 - finalNet / initialNet * 100)

    def get_coin_name(self) -> str:
        """
        Returns target coin name.
        Function assumes trader is using a coin paired with USDT.
        """
        temp = self.dataView.symbol.upper().split('USDT')
        return temp[0]

    def get_position(self) -> str:
        """
        Returns current position.
        :return: Current position integer bot is in.
        """
        return self.currentPosition

    def get_average(self, movingAverage: str, parameter: str, value: int, dataObject: Data = None,
                    update: bool = True) -> float:
        """
        Returns the moving average with parameter and value provided
        :param update: Boolean for whether average will call the API to get latest values or not.
        :param dataObject: Data object to be used to get moving averages.
        :param movingAverage: Moving average to get the average from the data view.
        :param parameter: Parameter for the data view to use in the moving average.
        :param value: Value for the moving average to use in the moving average.
        :return: A float value representing the moving average.
        """
        if dataObject is None:
            dataObject = self.dataView
        if movingAverage == 'SMA':
            return dataObject.get_sma(value, parameter, update=update)
        elif movingAverage == 'WMA':
            return dataObject.get_wma(value, parameter, update=update)
        elif movingAverage == 'EMA':
            return dataObject.get_ema(value, parameter, update=update)
        else:
            raise ValueError(f'Unknown moving average {movingAverage}.')

    def get_stop_loss(self) -> None or float:
        """
        Returns a stop loss for the position.
        :return: Stop loss value.
        """
        if self.currentPosition == SHORT:  # If we are in a short position.
            if self.lossStrategy == TRAILING_LOSS:  # This means we use trailing loss.
                return self.shortTrailingPrice * (1 + self.lossPercentageDecimal)
            elif self.lossStrategy == STOP_LOSS:  # This means we use the basic stop loss.
                return self.sellShortPrice * (1 + self.lossPercentageDecimal)
        elif self.currentPosition == LONG:  # If we are in a long position.
            if self.lossStrategy == TRAILING_LOSS:  # This means we use trailing loss.
                return self.longTrailingPrice * (1 - self.lossPercentageDecimal)
            elif self.lossStrategy == STOP_LOSS:  # This means we use the basic stop loss.
                return self.buyLongPrice * (1 - self.lossPercentageDecimal)
        else:  # This means we are not in any position currently.
            return None

    def get_trend(self, dataObject: Data = None, log_data=True) -> int or None:
        """
        Checks whether there is a trend or not.
        :param log_data: Boolean that will determine if data will be logged or not.
        :param dataObject: Data object to be used to check if there is a trend or not.
        :return: Integer specifying trend.
        """
        if len(self.tradingOptions) == 0:  # Checking whether options exist.
            raise ValueError("No trading options provided.")

        trends = []

        if dataObject is None:
            dataObject = self.dataView

        if not dataObject.data_is_updated():
            dataObject.update_data()

        dataObject.data.insert(0, dataObject.get_current_data())

        if dataObject == self.dataView:
            self.optionDetails = []
        else:
            self.lowerOptionDetails = []

        for option in self.tradingOptions:
            initialAverage = self.get_average(option.movingAverage, option.parameter, option.initialBound,
                                              dataObject, update=False)
            finalAverage = self.get_average(option.movingAverage, option.parameter, option.finalBound, dataObject,
                                            update=False)
            initialName, finalName = option.get_pretty_option()

            if dataObject == self.dataView:
                if log_data:
                    self.output_message(f'Regular interval ({dataObject.interval}) data:')
                self.optionDetails.append((initialAverage, finalAverage, initialName, finalName))
            else:
                if log_data:
                    self.output_message(f'Lower interval ({dataObject.interval}) data:')
                self.lowerOptionDetails.append((initialAverage, finalAverage, initialName, finalName))

            if log_data:
                self.output_message(f'{option.movingAverage}({option.initialBound}) = {initialAverage}')
                self.output_message(f'{option.movingAverage}({option.finalBound}) = {finalAverage}')

            if initialAverage > finalAverage:
                trends.append(BULLISH)
            elif initialAverage < finalAverage:
                trends.append(BEARISH)
            else:
                trends.append(None)

        dataObject.data = dataObject.data[1:]

        if all(trend == BULLISH for trend in trends):
            return BULLISH
        elif all(trend == BEARISH for trend in trends):
            return BEARISH
        else:
            return None

    def check_cross(self, dataObject: Data = None, log_data=True) -> bool:
        """
        Checks whether there is a true cross or not. If there is a trend, but the same trend was in the previous
        position, no action is taken.
        :param log_data: Boolean that will determine whether data is logged or not.
        :param dataObject: Data object to be used to check if there is a trend or not.
        :return: Boolean whether there is a cross or not.
        """
        self.trend = self.get_trend(dataObject, log_data=log_data)  # Get the trend.
        if self.trend == BULLISH:  # If the sign is bullish; meaning enter long.
            if self.currentPosition == LONG:  # We are already in a long position.
                return False
            elif self.currentPosition is None and self.previousPosition == LONG:  # This means stop loss occurred.
                return False
            else:  # We were not in a long position before, so this is a sign to enter.
                return True
        elif self.trend == BEARISH:  # If the sign is bearish; meaning enter short.
            if self.currentPosition == SHORT:  # We are already in a short position.
                return False
            elif self.currentPosition is None and self.previousPosition == SHORT:  # This means stop loss occurred.
                return False
            else:  # We were not in a short position before, so this is a sign to enter.
                return True
        return False  # There is no trend, so don't do anything.

    def output_trade_options(self):
        """
        Outputs general information about current trade options.
        """
        for option in self.tradingOptions:
            initialAverage = self.get_average(option.movingAverage, option.parameter, option.initialBound)
            finalAverage = self.get_average(option.movingAverage, option.parameter, option.finalBound)

            self.output_message(f'Parameter: {option.parameter}')
            self.output_message(f'{option.movingAverage}({option.initialBound}) = {initialAverage}')
            self.output_message(f'{option.movingAverage}({option.finalBound}) = {finalAverage}')

    def output_no_position_information(self):
        """
        Outputs general information about status of bot when not in a position.
        """
        if self.currentPosition is None:
            if not self.inHumanControl:
                self.output_message(f'\nCurrently not a in short or long position. Waiting for next cross.')
            else:
                self.output_message(f'\nCurrently not a in short or long position. Waiting for human intervention.')

    def output_short_information(self):
        """
        Outputs general information about status of trade when in a short position.
        """
        if self.currentPosition == SHORT:
            self.output_message(f'\nCurrently in short position.')
            if self.lossStrategy == TRAILING_LOSS:
                shortTrailingLossValue = round(self.shortTrailingPrice * (1 + self.lossPercentageDecimal), 2)
                self.output_message(f'Short trailing loss: ${shortTrailingLossValue}')
            elif self.lossStrategy == STOP_LOSS:
                self.output_message(f'Stop loss: {round(self.sellShortPrice * (1 + self.lossPercentageDecimal), 2)}')

    def output_long_information(self):
        """
        Outputs general information about status of trade when in a long position.
        """
        if self.currentPosition == LONG:
            self.output_message(f'\nCurrently in long position.')
            if self.lossStrategy == TRAILING_LOSS:
                longTrailingLossValue = round(self.longTrailingPrice * (1 - self.lossPercentageDecimal), 2)
                self.output_message(f'Long trailing loss: ${longTrailingLossValue}')
            elif self.lossStrategy == STOP_LOSS:
                self.output_message(f'Stop loss: {round(self.buyLongPrice * (1 - self.lossPercentageDecimal), 2)}')

    def output_control_mode(self):
        """
        Outputs general information about status of bot.
        """
        if self.inHumanControl:
            self.output_message(f'Currently in human control. Bot is waiting for human input to continue.')
        else:
            self.output_message(f'Currently in autonomous mode.')

    def output_profit_information(self):
        """
        Outputs general information about profit.
        """
        profit = round(self.get_profit(), 2)
        if profit > 0:
            self.output_message(f'Profit: ${profit}')
        elif profit < 0:
            self.output_message(f'Loss: ${-profit}')
        else:
            self.output_message(f'No profit or loss currently.')

    def output_basic_information(self):
        """
        Prints out basic information about trades.
        """
        self.output_message('---------------------------------------------------')
        self.output_message(f'Current time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        self.output_control_mode()

        if self.currentPrice is None:
            self.currentPrice = self.dataView.get_current_price()

        if self.currentPrice * self.coin > 5:  # If total worth of coin owned is more than $5, assume we're in long.
            self.output_message(f'{self.coinName} owned: {self.coin}')
            self.output_message(f'Price bot bought {self.coinName} long for: ${self.buyLongPrice}')

        if self.currentPrice * self.coinOwed > 5:  # If total worth of coin owed is more than $5, assume we're in short.
            self.output_message(f'{self.coinName} owed: {self.coinOwed}')
            self.output_message(f'Price bot sold {self.coinName} short for: ${self.sellShortPrice}')

        if self.currentPosition == LONG:
            self.output_long_information()
        elif self.currentPosition == SHORT:
            self.output_short_information()
        elif self.currentPosition is None:
            self.output_no_position_information()

        self.output_message(f'\nCurrent {self.coinName} price: ${self.currentPrice}')
        self.output_message(f'Balance: ${round(self.balance, 2)}')
        self.output_profit_information()
        if type(self) == SimulationTrader:
            self.output_message(f'\nTrades conducted this simulation: {len(self.trades)}')
        else:
            self.output_message(f'\nTrades conducted in live market: {len(self.trades)}')
        self.output_message('')

    def get_simulation_result(self):
        """
        Gets end result of simulation.
        """
        self.output_message('\n---------------------------------------------------\nSimulation has ended')
        self.endingTime = datetime.utcnow()
        if self.coin > 0:
            self.output_message(f"Selling all {self.coinName}...")
            self.sell_long(f'Sold all owned coin as simulation ended.')

        if self.coinOwed > 0:
            self.output_message(f"Returning all borrowed {self.coinName}...")
            self.buy_short(f'Returned all borrowed coin as simulation ended.')

        self.output_message("\nResults:")
        self.output_message(f'Starting time: {self.startingTime.strftime("%Y-%m-%d %H:%M:%S")}')
        self.output_message(f'End time: {self.endingTime.strftime("%Y-%m-%d %H:%M:%S")}')
        self.output_message(f'Elapsed time: {self.endingTime - self.startingTime}')
        self.output_message(f'Starting balance: ${self.startingBalance}')
        self.output_message(f'Ending balance: ${round(self.balance, 2)}')
        self.output_message(f'Trades conducted: {len(self.trades)}')
        self.output_profit_information()

    def log_trades_and_daily_net(self):
        """
        Logs trades.
        """
        self.output_message(f'\n\nTotal trade(s) in previous simulation: {len(self.trades)}')
        for counter, trade in enumerate(self.trades, 1):
            self.output_message(f'\n{counter}. Date in UTC: {trade["date"]}')
            self.output_message(f'\nAction taken: {trade["action"]}')

        self.output_message('\nDaily Nets:')

        for index, net in enumerate(self.dailyChangeNets, start=1):
            self.output_message(f'Day {index}: {round(net, 2)}%')

        self.output_message("")
