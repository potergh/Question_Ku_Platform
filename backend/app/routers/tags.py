"""Tag router — CRUD + tree structure."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Tag
from app.schemas.tag import TagResponse, TagCreate, TagUpdate, TagTree

router = APIRouter()


@router.get("/api/tags", response_model=list[TagResponse])
async def list_tags(
    category: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List all tags, optionally filtered by category and/or subject."""
    query = select(Tag).order_by(Tag.subject, Tag.category, Tag.name)
    if category:
        query = query.where(Tag.category == category)
    if subject:
        query = query.where(Tag.subject == subject)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/api/tags/tree", response_model=list[TagTree])
async def get_tag_tree(db: AsyncSession = Depends(get_db)):
    """Get tags organized as a tree (root tags with children)."""
    result = await db.execute(select(Tag).order_by(Tag.category, Tag.name))
    all_tags = result.scalars().all()

    # Build tree
    tag_map = {t.id: TagTree(id=t.id, name=t.name, category=t.category, color=t.color, parent_id=t.parent_id) for t in all_tags}
    roots = []
    for t in all_tags:
        node = tag_map[t.id]
        if t.parent_id and t.parent_id in tag_map:
            tag_map[t.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


@router.post("/api/tags", response_model=TagResponse)
async def create_tag(data: TagCreate, db: AsyncSession = Depends(get_db)):
    """Create a new tag."""
    tag = Tag(
        name=data.name,
        subject=data.subject,
        category=data.category,
        color=data.color,
        parent_id=data.parent_id,
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


@router.put("/api/tags/{tag_id}", response_model=TagResponse)
async def update_tag(tag_id: str, data: TagUpdate, db: AsyncSession = Depends(get_db)):
    """Update a tag."""
    tag = await db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tag, field, value)
    await db.commit()
    await db.refresh(tag)
    return tag


@router.delete("/api/tags/{tag_id}")
async def delete_tag(tag_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a tag (and its children recursively)."""
    tag = await db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")

    # Delete children first
    result = await db.execute(select(Tag).where(Tag.parent_id == tag_id))
    for child in result.scalars().all():
        await db.delete(child)

    await db.delete(tag)
    await db.commit()
    return {"ok": True}
