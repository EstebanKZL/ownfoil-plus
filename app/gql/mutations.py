"""Mutation root: library-domain writes.

Scope is deliberately narrow. Settings, users and the keys upload stay on REST -
they are form-and-file shaped, not graph shaped. What lives here is everything a
library page needs to act on what it is displaying: enqueue work, cancel work, and
edit title metadata.

Two conventions differ from the query side, both on purpose:

- **Denial raises.** Queries return `None` for a field a role cannot read, which is
  the right shape for a partial result. A write that is silently ignored is not a
  partial result, it is a lie, so these raise instead.
- **Nothing is cached.** `view.graphql_dispatch` skips the ETag and the 304 path
  entirely for mutations - see `is_mutation` there.

Every resolver delegates; no business logic lives in this module.
"""
from typing import Optional

import strawberry
from strawberry.types import Info
from typing_extensions import Annotated

from constants import COMPRESS_EXT

from .docs import described, described_mutation
from .resolvers import resolve_task, resolve_title
from .types import Task, Title


class NotAuthorized(Exception):
    """Raised when a role may not perform a write. Surfaces as a GraphQL error."""


class MutationFailed(Exception):
    """A write that was refused on its merits (unknown task, wrong file state)."""


def _require_admin(ctx) -> None:
    if not ctx.can_admin:
        raise NotAuthorized("Admin access is required for this operation.")


def _task_by_id(task_id, info) -> Optional[Task]:
    """Re-read a task through the query resolver so a mutation returns exactly what
    `task(id:)` would - one shape for a task, however the client got there."""
    return resolve_task(str(task_id), info.context, info)


@described(strawberry.type)
class Mutation:
    """Library-domain writes: enqueue work, cancel work, edit title metadata.

    Deliberately narrow - settings, users and the keys upload stay on REST, being
    form-and-file shaped rather than graph shaped. Unlike the query side, a write a
    role may not perform raises rather than returning null: a silently ignored write
    is not a partial result, it is a lie. All of these require admin."""

    @described_mutation
    def enqueue_task(
        self, info: Info,
        name: Annotated[str, strawberry.argument(
            description="A registered task name, e.g. `process_library`. An "
                        "unknown name is refused.")],
        input: Annotated[Optional[str], strawberry.argument(
            description="The task's arguments as a JSON object string. Omit for a "
                        "task that takes none.")] = None,
    ) -> Optional[Task]:
        """Enqueue any registered task. `input` is a JSON object string, because the
        payload shape differs per task name. Enqueuing a duplicate returns the
        existing task rather than creating a second one."""
        import json
        import tasks as tasks_mod
        _require_admin(info.context)
        try:
            payload = json.loads(input) if input else {}
        except ValueError as e:
            raise MutationFailed(f"input is not valid JSON: {e}")
        if not isinstance(payload, dict):
            raise MutationFailed("input must be a JSON object")
        try:
            task, _created = tasks_mod.enqueue_task(name, payload)
        except ValueError as e:
            raise MutationFailed(str(e))
        return _task_by_id(task.id, info)

    @described_mutation
    def cancel_task(
        self, info: Info,
        id: Annotated[strawberry.ID, strawberry.argument(
            description="Primary key of the task to cancel.")],
    ) -> bool:
        """False when the task is unknown or already in a terminal state."""
        import tasks as tasks_mod
        _require_admin(info.context)
        return bool(tasks_mod.cancel_task(int(id)))

    @described_mutation
    def dismiss_task(
        self, info: Info,
        id: Annotated[strawberry.ID, strawberry.argument(
            description="Primary key of the failed task to remove.")],
    ) -> bool:
        """Clear one failed task. Failed tasks are kept so a failure survives a page
        reload, so this is how a task queue gets tidied once its failures have been
        read. False when the task is unknown or has not failed - a running or queued
        task is `cancelTask`'s job, not this one."""
        import tasks as tasks_mod
        _require_admin(info.context)
        return bool(tasks_mod.dismiss_task(int(id)))

    @described_mutation
    def purge_failed_tasks(self, info: Info) -> int:
        """Clear every failed task at once, returning how many were removed. Zero when
        there was nothing to clear, which is not an error."""
        import tasks as tasks_mod
        _require_admin(info.context)
        return tasks_mod.purge_failed_tasks()

    @described_mutation
    def scan_library(
        self, info: Info,
        path: Annotated[Optional[str], strawberry.argument(
            description="Absolute path of one configured library root. Omit to scan "
                        "every configured root.")] = None,
    ) -> Optional[Task]:
        """Scan one library, or every configured library when `path` is omitted. The
        all-libraries form returns the last task enqueued."""
        import tasks as tasks_mod
        from db import get_libraries
        _require_admin(info.context)
        if path:
            task, _ = tasks_mod.enqueue_task('scan_library', {'library_path': path})
            return _task_by_id(task.id, info)
        last = None
        for lib in get_libraries():
            last, _ = tasks_mod.enqueue_task('scan_library', {'library_path': lib.path})
        return _task_by_id(last.id, info) if last else None

    @described_mutation
    def verify_library(
        self, info: Info,
        force: Annotated[bool, strawberry.argument(
            description="Re-verify every eligible file regardless of its current "
                        "verdict, including ones already Valid - not just the ones "
                        "still missing one. Off by default: a plain call only picks "
                        "up files that were never checked (or were interrupted "
                        "mid-check), the same thing the automatic pipeline already "
                        "does on its own, so it never re-does work that already "
                        "settled. Meant for an explicit, deliberate re-check the "
                        "admin asked for - the UI should confirm before setting "
                        "this, since on a large library it can mean re-reading "
                        "everything from disk.")] = False,
    ) -> Task:
        """Verify every file that needs it, without first running a full Scan (which
        also discovers new files and re-organizes). Use this to resume a verification
        pass that was previously paused/cancelled, or to check the library on demand
        without touching identify/organize - Scan already triggers this same phase as
        part of its own pipeline, so this is only needed to trigger it on its own."""
        import tasks as tasks_mod
        _require_admin(info.context)
        task, _ = tasks_mod.enqueue_task('verify_library', {'force': force} if force else {})
        return _task_by_id(task.id, info)

    @described_mutation
    def compress_file(
        self, info: Info,
        file_id: Annotated[strawberry.ID, strawberry.argument(
            description="Primary key of the file to compress.")],
    ) -> Optional[Task]:
        """Compress one file to NSZ/XCZ. Same guards as the REST endpoint."""
        import tasks as tasks_mod
        from db import Files, db
        _require_admin(info.context)
        file = db.session.get(Files, int(file_id))
        if not file:
            raise MutationFailed("File not found")
        if file.compressed:
            raise MutationFailed("File is already compressed")
        if file.extension not in COMPRESS_EXT:
            raise MutationFailed("File type cannot be compressed")
        task, _ = tasks_mod.enqueue_task('compress_file', {'file_id': int(file_id)})
        return _task_by_id(task.id, info)

    @described_mutation
    def decompress_file(
        self, info: Info,
        file_id: Annotated[strawberry.ID, strawberry.argument(
            description="Primary key of the file to decompress.")],
    ) -> Optional[Task]:
        """Decompress one file back to NSP/XCI."""
        import tasks as tasks_mod
        from db import Files, db
        _require_admin(info.context)
        file = db.session.get(Files, int(file_id))
        if not file:
            raise MutationFailed("File not found")
        if not file.compressed:
            raise MutationFailed("File is not compressed")
        task, _ = tasks_mod.enqueue_task('decompress_file', {'file_id': int(file_id)})
        return _task_by_id(task.id, info)

    @described_mutation
    def verify_file(
        self, info: Info,
        file_id: Annotated[strawberry.ID, strawberry.argument(
            description="Primary key of the file to verify.")],
    ) -> Optional[Task]:
        """Re-verify one file at the configured depth. The stored verdicts are cleared
        first, so this re-checks a file that already has them rather than no-opping."""
        import tasks as tasks_mod
        from containers import verification as verification_lib
        from db import Files, db, reset_file_verification
        _require_admin(info.context)
        file = db.session.get(Files, int(file_id))
        if not file:
            raise MutationFailed("File not found")
        if file.extension not in verification_lib.VERIFY_EXT:
            raise MutationFailed("File type cannot be verified")
        reset_file_verification(file)
        db.session.commit()
        task, _ = tasks_mod.enqueue_task('verify_file', {'file_id': int(file_id)})
        return _task_by_id(task.id, info)

    @described_mutation
    def set_title_override(
        self, info: Info,
        title_id: Annotated[strawberry.ID, strawberry.argument(
            description="The 16-hex-digit title id to override.")],
        record: Annotated[str, strawberry.argument(
            description="A JSON object of metadata fields to override. Fields it "
                        "omits keep their downloaded values.")],
    ) -> Optional[Title]:
        """Write user-authored metadata for a title, winning over the downloaded
        titledb values field by field. `record` is a JSON object of the same shape the
        REST endpoint takes. Re-identification is enqueued, as there too."""
        import json
        import tasks as tasks_mod
        import titledb
        _require_admin(info.context)
        try:
            payload = json.loads(record)
        except ValueError as e:
            raise MutationFailed(f"record is not valid JSON: {e}")
        if not isinstance(payload, dict):
            raise MutationFailed("record must be a JSON object")
        ok, err = titledb.store.set_override(str(title_id), payload)
        if not ok:
            raise MutationFailed(err)
        tasks_mod.enqueue_task('process_library')
        return resolve_title(str(title_id), info.context, info)

    @described_mutation
    def delete_title_override(
        self, info: Info,
        title_id: Annotated[strawberry.ID, strawberry.argument(
            description="The 16-hex-digit title id whose override to drop.")],
    ) -> bool:
        """Drop the override, restoring the next metadata source down."""
        import titledb
        _require_admin(info.context)
        ok, _err = titledb.store.delete_override(str(title_id))
        return bool(ok)

    @described_mutation
    def resolve_duplicate_files(
        self, info: Info,
        keep_file_id: Annotated[strawberry.ID, strawberry.argument(
            description="Which file, among its app's duplicates, to keep. Every "
                        "other file currently attached to the same app is deleted, "
                        "and this one is renamed to drop any \"(n)\" collision "
                        "suffix if the plain name is now free.")],
    ) -> bool:
        """Manually resolve a duplicate: keep one file, delete its app's other
        copies. Unlike the automatic pass (which only ever acts when every copy's
        verification verdict is unambiguous), this acts on whatever `keepFileId` is
        given regardless of verdict - a person choosing from `duplicateFileGroups`
        has already made the call themselves."""
        import library
        from db import db, Files
        _require_admin(info.context)
        file_obj = db.session.get(Files, int(keep_file_id))
        if file_obj is None:
            raise MutationFailed(f"No file with id {keep_file_id}.")
        if not file_obj.apps:
            raise MutationFailed(f"File {keep_file_id} is not attached to any app.")
        all_ids = [f.id for f in file_obj.apps[0].files]
        if len(all_ids) < 2:
            raise MutationFailed(f"File {keep_file_id} has no duplicates to resolve.")
        return library.resolve_duplicate_files(file_obj.id, all_ids)

    @described_mutation
    def resolve_duplicates_by_size(
        self, info: Info,
        compression_preference: Annotated[Optional[str], strawberry.argument(
            description="Checked before size, for a group whose tied copies aren't "
                        "all the same compression status: 'compressed' or "
                        "'uncompressed' to prefer that side regardless of which one "
                        "happens to be bigger, or omit/'none' for pure size (the "
                        "original behavior - a compressed file is always the smaller "
                        "one, so without this a mixed nsp/nsz batch would always keep "
                        "the uncompressed copy).")] = None,
    ) -> int:
        """Bulk-resolve every current duplicate group that can be decided safely
        right now. Within each group's own tied copies: `compressionPreference`
        (if given, and if the tied copies aren't all the same compression status)
        decides first, then whichever copy is larger settles anything it doesn't -
        the same two-step rule `duplicateWinnerWithPreferences` uses for the opt-in
        automatic setting, just triggered immediately for every eligible group in one
        call instead of one at a time. A group containing any unverified, modified, or
        signature-only file is still skipped entirely - the same safety gate applies
        regardless of this being a manual, explicit action. Returns how many groups
        were resolved, so the caller can tell "nothing left to do" from "actually
        cleaned something up" without a second query."""
        import library
        _require_admin(info.context)
        pref = compression_preference if compression_preference in ('compressed', 'uncompressed') else 'none'
        resolved = 0
        for app, files in library.duplicate_file_groups():
            winner = library.duplicate_winner_with_preferences(
                files, prefer_larger_on_tie=True, compression_preference=pref)
            if winner is None:
                continue
            library.resolve_duplicate_files(winner.id, [f.id for f in files])
            resolved += 1
        return resolved
