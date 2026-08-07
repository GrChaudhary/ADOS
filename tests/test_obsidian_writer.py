"""
Tests for Obsidian atomic deduplicated VaultWriter.
"""

import pytest
from orchestrate.obsidian.writer import ObsidianVaultWriter


@pytest.mark.asyncio
async def test_obsidian_writer_deduplication(tmp_path):
    writer = ObsidianVaultWriter(target_dir=tmp_path)

    note_path = "01_Domain_Pods/TestPod.md"
    content = "# Test Pod Note\nThis is a test."

    # First write -> True
    written1 = await writer.write_note(note_path, content)
    assert written1 is True
    assert (tmp_path / note_path).exists()
    assert (tmp_path / note_path).read_text(encoding="utf-8") == content

    # Second write with identical content -> False (Deduplicated!)
    written2 = await writer.write_note(note_path, content)
    assert written2 is False

    # Third write with updated content -> True
    updated_content = "# Test Pod Note\nUpdated content."
    written3 = await writer.write_note(note_path, updated_content)
    assert written3 is True
    assert (tmp_path / note_path).read_text(encoding="utf-8") == updated_content
