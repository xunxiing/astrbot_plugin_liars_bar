# -*- coding: utf-8 -*-

class GameError(Exception):
    """Base exception for game logic errors."""
    pass

class GameNotFoundError(GameError):
    """Game instance not found."""
    pass

class PlayerNotInGameError(GameError):
    """Player is not part of the game."""
    pass

class PlayerAlreadyJoinedError(GameError):
    """Player trying to join again."""
    pass

class GameNotWaitingError(GameError):
    """Action requires game state to be WAITING."""
    pass

class GameNotPlayingError(GameError):
    """Action requires game state to be PLAYING."""
    pass

class NotEnoughPlayersError(GameError):
    """Not enough players to start the game."""
    pass

class NotPlayersTurnError(GameError):
    """Attempted action when it's not the player's turn."""
    def __init__(self, message="Attempted action when it's not the player's turn.", current_player_name=None):
        super().__init__(message)
        self.current_player_name = current_player_name # 可以携带当前玩家名字

class InvalidActionError(GameError):
    """Player attempting an action not allowed in the current context (e.g., waiting with cards)."""
    pass

class InvalidCardIndexError(GameError):
    """Provided card indices are invalid (out of bounds, duplicates)."""
    def __init__(self, message="Provided card indices are invalid.", invalid_indices=None, hand_size=None):
        super().__init__(message)
        self.invalid_indices = invalid_indices
        self.hand_size = hand_size


class InvalidPlayQuantityError(GameError):
    """Attempting to play an invalid number of cards."""
    pass

class NoChallengeTargetError(GameError):
    """Trying to challenge when there's no active play to challenge."""
    pass

class EmptyHandError(GameError):
     """Attempting an action (like playing cards) that requires cards, but hand is empty."""
     pass
