from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.challenge.models import Challenge
from app.shared.timezones import local_today
from app.streaks.engine import ChallengeFacts, MemberFacts, StreakResult, calculate
from app.streaks.repository import StreakRepository


class StreakService:
    def __init__(self, repository: StreakRepository):
        self.repository = repository

    async def recalculate(self, db: AsyncSession, challenge: Challenge) -> StreakResult:
        """Recomputes every streak for a challenge and stores the answer.

        The stored counters are a cache of what the check-ins already say, so
        this is safe to call as often as needed: it is idempotent, and running
        it twice in a row changes nothing the second time.
        """
        rows = await self.repository.find_members_with_users(db, challenge.id)
        counting_days = await self.repository.find_counting_days(db, challenge.id)
        covered = {(user_id, day) for user_id, day in counting_days}

        members = [
            MemberFacts(
                member_id=member.id,
                user_id=member.user_id,
                local_today=local_today(user.timezone),
                # The join instant seen from the member's own calendar: joining at
                # 23:00 in Bogotá is a different day than the UTC timestamp shows.
                joined_local_date=member.joined_at.astimezone(ZoneInfo(user.timezone)).date(),
                inherited_missed_days=member.inherited_missed_days,
            )
            for member, user in rows
        ]

        result = calculate(
            ChallengeFacts(
                start_date=challenge.start_date,
                end_date=challenge.end_date,
                active_days=challenge.active_days,
            ),
            members,
            covered,
        )

        changed = False
        if (challenge.current_group_streak, challenge.best_group_streak) != (
            result.current_group_streak,
            max(result.best_group_streak, challenge.best_group_streak),
        ):
            challenge.current_group_streak = result.current_group_streak
            # The record stands even if the history it came from is later edited away.
            challenge.best_group_streak = max(result.best_group_streak, challenge.best_group_streak)
            db.add(challenge)
            changed = True

        for member, _ in rows:
            streaks = result.members[member.id]
            best = max(streaks.best_individual_streak, member.best_individual_streak)
            if (
                member.current_individual_streak,
                member.best_individual_streak,
                member.missed_days_count,
            ) != (streaks.current_individual_streak, best, streaks.missed_days_count):
                member.current_individual_streak = streaks.current_individual_streak
                member.best_individual_streak = best
                member.missed_days_count = streaks.missed_days_count
                db.add(member)
                changed = True

        # Writing nothing when nothing moved keeps plain reads from touching the
        # database on every request.
        if changed:
            await db.commit()
            # The UPDATE fires the challenge's onupdate timestamp, so SQLAlchemy
            # marks updated_at as stale. Reading it later would need a lazy query
            # that async code cannot run, which is a MissingGreenlet at response
            # time; refreshing here loads it while we are still allowed to.
            await db.refresh(challenge)

        return result


streak_service = StreakService(StreakRepository())
