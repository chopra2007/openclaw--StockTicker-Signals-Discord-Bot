"""Append-only transition storage through the host's injected database handle.

Never obtains a default database, initializes a database or opens a path. The
caller owns the connection and uses the existing migrations. Full input/feature
storage, candidate/delivery transactions and recovery belong to M5.
"""

from .db import AsyncConnection
from .state_transitions import TransitionEntry, TransitionScope
from .trade_alerts_models import RecordError, StrategyStateTransition


class SQLiteTransitionStore:
    def __init__(self, connection: AsyncConnection):
        self._connection = connection

    async def append(self, entry: TransitionEntry) -> None:
        scope = entry.scope
        values = (entry.transition.record_id, scope.stream_id, entry.position,
                  entry.previous_record_id, scope.to_json(), entry.transition.to_json())
        # The predecessor and scope check is inside the existing transaction.
        # Unique stream/position prevents two owners appending competing facts.
        await self._connection.execute_transaction([(
            """INSERT INTO trade_alerts_transitions_v1
               (record_id, stream_id, position, previous_record_id, scope_json, transition_json)
               SELECT ?, ?, ?, ?, ?, ?
               WHERE (? = 1 AND NOT EXISTS (
                   SELECT 1 FROM trade_alerts_transitions_v1 WHERE stream_id = ?))
               OR EXISTS (SELECT 1 FROM trade_alerts_transitions_v1
                   WHERE stream_id = ? AND position = ? AND record_id = ? AND scope_json = ?)
               ON CONFLICT(record_id) DO NOTHING""",
            (*values, entry.position, scope.stream_id, scope.stream_id,
             entry.position - 1, entry.previous_record_id, scope.to_json()),
        )])
        cursor = await self._connection.execute(
            """SELECT record_id, stream_id, position, previous_record_id, scope_json, transition_json
               FROM trade_alerts_transitions_v1 WHERE record_id = ?""", (entry.transition.record_id,),
        )
        row = await cursor.fetchone()
        if row is None or tuple(row) != values:
            raise RecordError("stored transition conflicts with identity, scope or predecessor")

    async def read(self, scope: TransitionScope) -> tuple[TransitionEntry, ...]:
        """Read ordered canonical facts; this does not restore strategy state."""
        cursor = await self._connection.execute(
            """SELECT position, previous_record_id, scope_json, transition_json
               FROM trade_alerts_transitions_v1 WHERE stream_id = ? ORDER BY position""",
            (scope.stream_id,),
        )
        result = []
        for row in await cursor.fetchall():
            if row[2] != scope.to_json():
                raise RecordError("stored transition scope differs from requested scope")
            result.append(TransitionEntry(
                scope, row[0], row[1], StrategyStateTransition.from_json(row[3]),
            ))
        return tuple(result)
