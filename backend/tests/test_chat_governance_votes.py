"""Chat Governance Phase 2 — reusable vote-action foundation tests."""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.domains.governance.vote_service import VoteError, VoteService
from app.domains.members.profile import NicknameChangePolicy
from app.models.chat_vote_action import ChatVoteAction, ChatVoteStatus
from app.models.chat_vote_ballot import ChatVoteBallot


def _user(*, nickname, role="member", display_role=None, session_id=None, user_id=None):
    return types.SimpleNamespace(
        id=user_id or uuid.uuid4(),
        session_id=session_id or uuid.uuid4(),
        username=nickname.lower().replace(" ", "_"),
        nickname=nickname,
        display_role=display_role,
        role=types.SimpleNamespace(value=role),
        avatar_url=None,
    )


class DummyDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def flush(self):
        return None


class FakeVoteRepository:
    def __init__(self, *, members, active_count=None):
        self.db = DummyDb()
        self.members_by_session = {str(member.session_id): member for member in members}
        self.users_by_key = {str(member.id): member for member in members}
        self.active_count = active_count if active_count is not None else len(members)
        self.group = types.SimpleNamespace(id=1)
        self.actions = {}
        self.ballots = {}
        self.messages = []
        self.next_id = 1
        self.next_message_id = 100
        self.updated_nicknames = []
        self.updated_display_roles = []

    async def default_group(self):
        return self.group

    async def get_active_member_by_session_id(self, group_id, session_id):
        return self.members_by_session.get(str(session_id))

    async def count_active_members(self, group_id):
        return self.active_count

    async def create_action(self, action):
        action.id = self.next_id
        self.next_id += 1
        self.actions[action.id] = action
        return action

    async def post_bot_message(self, content):
        message = types.SimpleNamespace(
            id=self.next_message_id,
            content=content,
            created_at=datetime.utcnow(),
        )
        self.next_message_id += 1
        self.messages.append(message)
        return message

    async def set_open_message_id(self, action, message_id):
        action.open_message_id = message_id

    async def set_result_message_id(self, action, message_id):
        action.result_message_id = message_id

    async def get_action(self, vote_action_id):
        return self.actions.get(vote_action_id)

    async def list_actions(self, group_id, statuses=None):
        actions = [action for action in self.actions.values() if action.group_id == group_id]
        if statuses:
            actions = [action for action in actions if action.status in statuses]
        return sorted(actions, key=lambda action: action.id, reverse=True)

    async def get_ballot(self, vote_action_id, user_id):
        return self.ballots.get((vote_action_id, str(user_id)))

    async def upsert_ballot(self, vote_action_id, user_id, vote):
        key = (vote_action_id, str(user_id))
        existing = self.ballots.get(key)
        if existing:
            existing.vote = vote
            existing.updated_at = datetime.utcnow()
            return existing
        ballot = types.SimpleNamespace(
            id=len(self.ballots) + 1,
            vote_action_id=vote_action_id,
            user_id=user_id,
            vote=vote,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.ballots[key] = ballot
        return ballot

    async def recalculate_counts(self, action):
        votes = [ballot.vote for (action_id, _), ballot in self.ballots.items() if action_id == action.id]
        action.yes_count = votes.count("yes")
        action.no_count = votes.count("no")
        action.updated_at = datetime.utcnow()
        return action.yes_count, action.no_count

    async def get_user_votes(self, vote_action_ids, user_id):
        return {
            action_id: ballot.vote
            for (action_id, ballot_user_id), ballot in self.ballots.items()
            if action_id in vote_action_ids and ballot_user_id == str(user_id)
        }

    async def users_by_id(self, user_ids):
        return {str(user_id): self.users_by_key[str(user_id)] for user_id in user_ids if user_id and str(user_id) in self.users_by_key}

    async def set_action_status(self, action, *, status, resolved_by_user_id=None):
        action.status = status
        action.resolved_at = datetime.utcnow()
        action.updated_at = action.resolved_at
        action.resolved_by_user_id = resolved_by_user_id
        return action

    async def update_target_nickname(self, target_user_id, nickname):
        self.updated_nicknames.append((target_user_id, nickname))
        user = self.users_by_key[str(target_user_id)]
        user.nickname = nickname

    async def update_target_display_role(self, target_user_id, display_role):
        self.updated_display_roles.append((target_user_id, display_role))
        user = self.users_by_key[str(target_user_id)]
        user.display_role = display_role

    async def open_expired_actions(self, now):
        return [
            action for action in self.actions.values()
            if action.status == ChatVoteStatus.open.value and action.expires_at <= now
        ]


class TestMigrationAndModels(unittest.TestCase):
    def test_migration_exists_with_tables_and_constraints(self):
        repo_root = Path(__file__).resolve().parents[2]
        migration = repo_root / "backend" / "migrations" / "032_chat_vote_actions.sql"
        self.assertTrue(migration.exists())
        body = migration.read_text(encoding="utf-8")
        for fragment in (
            "CREATE TABLE IF NOT EXISTS chat_vote_actions",
            "CREATE TABLE IF NOT EXISTS chat_vote_ballots",
            "nickname_change",
            "UNIQUE (vote_action_id, user_id)",
            "vote IN ('yes', 'no')",
        ):
            self.assertIn(fragment, body)

    def test_model_columns_present(self):
        action_cols = {column.key for column in ChatVoteAction.__table__.columns}
        ballot_cols = {column.key for column in ChatVoteBallot.__table__.columns}
        for name in (
            "group_id",
            "created_by_user_id",
            "target_user_id",
            "action_type",
            "status",
            "payload_json",
            "threshold_type",
            "threshold_value",
            "yes_count",
            "no_count",
            "expires_at",
            "resolved_at",
            "open_message_id",
            "result_message_id",
        ):
            self.assertIn(name, action_cols)
        for name in ("vote_action_id", "user_id", "vote", "created_at", "updated_at"):
            self.assertIn(name, ballot_cols)


class TestVoteService(unittest.TestCase):
    def setUp(self):
        self.luke = _user(nickname="Luke")
        self.tom = _user(nickname="Tom")
        self.ryan = _user(nickname="Ryan")
        self.repo = FakeVoteRepository(members=[self.luke, self.tom, self.ryan])
        self.service = VoteService(self.repo)

    def _create_vote(self, **kwargs):
        return asyncio.run(self.service.create_nickname_vote(
            proposer=kwargs.get("proposer", self.luke),
            target_session_id=str(kwargs.get("target", self.tom).session_id),
            proposed_nickname=kwargs.get("nickname", "Taxi Tom"),
            reason=kwargs.get("reason"),
            expires_at=kwargs.get("expires_at"),
            policy=kwargs.get("policy", NicknameChangePolicy.self_edit),
        ))

    def test_create_nickname_vote(self):
        payload = self._create_vote()
        self.assertEqual(payload["action_type"], "nickname_change")
        self.assertEqual(payload["status"], "open")
        self.assertEqual(payload["threshold_type"], "active_member_majority")
        self.assertEqual(payload["threshold_value"], 2)
        self.assertEqual(payload["payload"]["target_session_id"], str(self.tom.session_id))
        self.assertEqual(payload["payload"]["current_nickname"], "Tom")
        self.assertEqual(payload["payload"]["proposed_nickname"], "Taxi Tom")

    def test_create_display_role_vote(self):
        payload = asyncio.run(self.service.create_display_role_vote(
            proposer=self.luke,
            target_session_id=str(self.tom.session_id),
            proposed_display_role="Pub Secretary",
            reason="Keeps track of plans",
        ))
        self.assertEqual(payload["action_type"], "display_role_change")
        self.assertEqual(payload["status"], "open")
        self.assertEqual(payload["threshold_value"], 2)
        self.assertEqual(payload["payload"]["target_session_id"], str(self.tom.session_id))
        self.assertEqual(payload["payload"]["target_nickname"], "Tom")
        self.assertEqual(payload["payload"]["current_display_role"], "Citizen")
        self.assertEqual(payload["payload"]["proposed_display_role"], "Pub Secretary")
        self.assertEqual(payload["payload"]["reason"], "Keeps track of plans")

    def test_create_display_role_vote_uses_existing_role(self):
        self.tom.display_role = "Jester"
        payload = asyncio.run(self.service.create_display_role_vote(
            proposer=self.luke,
            target_session_id=str(self.tom.session_id),
            proposed_display_role="Pub Secretary",
        ))
        self.assertEqual(payload["payload"]["current_display_role"], "Jester")

    def test_reject_blank_nickname(self):
        with self.assertRaises(VoteError) as ctx:
            self._create_vote(nickname=" ")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reject_blank_display_role(self):
        with self.assertRaises(VoteError) as ctx:
            asyncio.run(self.service.create_display_role_vote(
                proposer=self.luke,
                target_session_id=str(self.tom.session_id),
                proposed_display_role=" ",
            ))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reject_target_outside_group(self):
        outsider = _user(nickname="Outsider")
        with self.assertRaises(VoteError) as ctx:
            self._create_vote(target=outsider)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_reject_proposer_outside_group(self):
        outsider = _user(nickname="Outsider")
        with self.assertRaises(VoteError) as ctx:
            self._create_vote(proposer=outsider)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_respects_admin_only_policy(self):
        with self.assertRaises(VoteError) as ctx:
            self._create_vote(policy=NicknameChangePolicy.admin_only)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_can_create_under_admin_only_policy(self):
        admin = _user(nickname="Admin", role="admin")
        repo = FakeVoteRepository(members=[admin, self.tom, self.ryan])
        service = VoteService(repo)
        payload = asyncio.run(service.create_nickname_vote(
            proposer=admin,
            target_session_id=str(self.tom.session_id),
            proposed_nickname="Taxi Tom",
            policy=NicknameChangePolicy.admin_only,
        ))
        self.assertEqual(payload["status"], "open")

    def test_cast_yes_vote(self):
        self._create_vote()
        result = asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="yes"))
        self.assertEqual(result["vote_action"]["yes_count"], 1)
        self.assertEqual(result["vote_action"]["no_count"], 0)
        self.assertFalse(result["resolved"])

    def test_cast_no_vote(self):
        self._create_vote()
        result = asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="no"))
        self.assertEqual(result["vote_action"]["yes_count"], 0)
        self.assertEqual(result["vote_action"]["no_count"], 1)

    def test_changing_vote_updates_counts_without_duplication(self):
        self._create_vote()
        asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="no"))
        result = asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="yes"))
        self.assertEqual(result["vote_action"]["yes_count"], 1)
        self.assertEqual(result["vote_action"]["no_count"], 0)
        self.assertEqual(len(self.repo.ballots), 1)

    def test_pass_threshold_updates_nickname(self):
        self._create_vote()
        asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="yes"))
        result = asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.ryan, vote="yes"))
        self.assertTrue(result["resolved"])
        self.assertEqual(result["vote_action"]["status"], "passed")
        self.assertEqual(self.tom.nickname, "Taxi Tom")
        self.assertEqual(self.repo.updated_nicknames, [(self.tom.id, "Taxi Tom")])

    def test_pass_threshold_updates_display_role(self):
        asyncio.run(self.service.create_display_role_vote(
            proposer=self.luke,
            target_session_id=str(self.tom.session_id),
            proposed_display_role="Pub Secretary",
        ))
        asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="yes"))
        result = asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.ryan, vote="yes"))
        self.assertTrue(result["resolved"])
        self.assertEqual(result["vote_action"]["status"], "passed")
        self.assertEqual(self.tom.display_role, "Pub Secretary")
        self.assertEqual(self.repo.updated_display_roles, [(self.tom.id, "Pub Secretary")])

    def test_expired_vote_does_not_update_nickname(self):
        self._create_vote()
        action = self.repo.actions[1]
        action.expires_at = datetime.utcnow() - timedelta(seconds=1)
        expired = asyncio.run(self.service.expire_votes())
        self.assertEqual(expired[0]["status"], "expired")
        self.assertEqual(self.tom.nickname, "Tom")
        self.assertEqual(self.repo.updated_nicknames, [])

    def test_cancelled_vote_cannot_be_voted_on(self):
        self._create_vote()
        asyncio.run(self.service.cancel_vote(vote_action_id=1, actor=self.luke))
        with self.assertRaises(VoteError) as ctx:
            asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.ryan, vote="yes"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_non_members_cannot_vote(self):
        self._create_vote()
        outsider = _user(nickname="Outsider")
        with self.assertRaises(VoteError) as ctx:
            asyncio.run(self.service.cast_vote(vote_action_id=1, voter=outsider, vote="yes"))
        self.assertEqual(ctx.exception.status_code, 403)


class TestVoteServiceChatMessages(unittest.TestCase):
    def setUp(self):
        self.luke = _user(nickname="Luke")
        self.tom = _user(nickname="Tom")
        self.ryan = _user(nickname="Ryan")
        self.repo = FakeVoteRepository(members=[self.luke, self.tom, self.ryan])
        self.service = VoteService(self.repo, enable_chat_messages=True)

    def _create_vote(self):
        return asyncio.run(self.service.create_nickname_vote(
            proposer=self.luke,
            target_session_id=str(self.tom.session_id),
            proposed_nickname="Taxi Tom",
            policy=NicknameChangePolicy.self_edit,
        ))

    def test_create_nickname_vote_creates_open_marker_message(self):
        payload = self._create_vote()
        self.assertEqual(payload["open_message_id"], 100)
        self.assertEqual(len(self.repo.messages), 1)
        self.assertIn("[[vote-action:1]]", self.repo.messages[0].content)
        self.assertEqual(self.repo.actions[1].open_message_id, 100)

    def test_passed_vote_creates_result_message(self):
        self._create_vote()
        asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="yes"))
        result = asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.ryan, vote="yes"))
        self.assertEqual(result["vote_action"]["status"], "passed")
        self.assertEqual(result["vote_action"]["result_message_id"], 101)
        self.assertEqual(len(self.repo.messages), 2)
        self.assertIn("Motion passed", self.repo.messages[1].content)
        self.assertIn("Taxi Tom", self.repo.messages[1].content)

    def test_passed_display_role_vote_creates_result_message(self):
        asyncio.run(self.service.create_display_role_vote(
            proposer=self.luke,
            target_session_id=str(self.tom.session_id),
            proposed_display_role="Pub Secretary",
        ))
        asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="yes"))
        result = asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.ryan, vote="yes"))
        self.assertEqual(result["vote_action"]["status"], "passed")
        self.assertEqual(result["vote_action"]["result_message_id"], 101)
        self.assertEqual(len(self.repo.messages), 2)
        self.assertIn("Motion passed", self.repo.messages[1].content)
        self.assertIn("Tom", self.repo.messages[1].content)
        self.assertIn("Pub Secretary", self.repo.messages[1].content)

    def test_cancelled_vote_creates_result_message(self):
        self._create_vote()
        result = asyncio.run(self.service.cancel_vote(vote_action_id=1, actor=self.luke))
        self.assertEqual(result["vote_action"]["status"], "cancelled")
        self.assertEqual(result["vote_action"]["result_message_id"], 101)
        self.assertEqual(len(self.repo.messages), 2)
        self.assertIn("Motion cancelled", self.repo.messages[1].content)

    def test_repeated_resolve_does_not_duplicate_result_message(self):
        self._create_vote()
        asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.luke, vote="yes"))
        asyncio.run(self.service.cast_vote(vote_action_id=1, voter=self.ryan, vote="yes"))
        first_count = len(self.repo.messages)
        result = asyncio.run(self.service.resolve_vote(vote_action_id=1, actor=self.luke))
        self.assertFalse(result["resolved"])
        self.assertEqual(len(self.repo.messages), first_count)


if __name__ == "__main__":
    unittest.main()
