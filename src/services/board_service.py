from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload, with_loader_criteria

from src.models.post import Comment, ContentReport, Post
from src.models.user import User
from src.schemas.post import PostCreate, PostUpdate
from src.utils.time import utc_now_naive


def _author(post: Post) -> tuple[str | None, str]:
    if post.is_anonymous:
        return None, "익명"
    return post.author_id, post.author.name if post.author else "탈퇴한 사용자"


def _post_item(post: Post) -> dict:
    author_id, author_name = _author(post)
    return {
        "id": post.id,
        "author_id": author_id,
        "author_name": author_name,
        "post_type": post.post_type,
        "title": post.title,
        "is_notice": post.is_notice,
        "board_scope": post.board_scope,
        "is_anonymous": post.is_anonymous,
        "created_at": post.created_at,
        "comment_count": sum(1 for comment in post.comments if not comment.is_deleted),
        "is_author_president": False,
    }


def _post_detail(post: Post) -> dict:
    author_id, author_name = _author(post)
    return {
        "id": post.id,
        "club_id": None,
        "author_id": author_id,
        "author_name": author_name,
        "post_type": post.post_type,
        "title": post.title,
        "content": post.content,
        "is_notice": post.is_notice,
        "board_scope": post.board_scope,
        "is_anonymous": post.is_anonymous,
        "created_at": post.created_at,
        "is_author_president": False,
        "comments": [
            {
                "id": comment.id,
                "post_id": comment.post_id,
                "author_id": comment.author_id,
                "author_name": comment.author.name if comment.author else "탈퇴한 사용자",
                "content": comment.content,
                "created_at": comment.created_at,
                "is_author_president": False,
            }
            for comment in post.comments
            if not comment.is_deleted
        ],
    }


def list_posts(
    db: Session, scope: str, page: int, size: int, search: str | None = None
) -> dict:
    query = db.query(Post).options(
        selectinload(Post.author), selectinload(Post.comments)
    ).filter(Post.board_scope == scope, Post.is_deleted.is_(False))
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(Post.title.ilike(pattern), Post.content.ilike(pattern)))
    total = query.count()
    posts = query.order_by(
        Post.is_notice.desc(), Post.created_at.desc(), Post.id.desc()
    ).offset((page - 1) * size).limit(size).all()
    return {
        "items": [_post_item(post) for post in posts],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }


def get_post(db: Session, scope: str, post_id: str) -> dict | None:
    post = db.query(Post).options(
        selectinload(Post.author),
        selectinload(Post.comments).selectinload(Comment.author),
        with_loader_criteria(Comment, Comment.is_deleted.is_(False)),
    ).filter(
        Post.id == post_id,
        Post.board_scope == scope,
        Post.is_deleted.is_(False),
    ).first()
    return _post_detail(post) if post else None


def create_post(
    db: Session, scope: str, user: User, data: PostCreate
) -> dict:
    if scope == "service" and data.is_anonymous:
        raise ValueError("서비스 공지는 익명으로 작성할 수 없습니다.")
    post = Post(
        club_id=None,
        board_scope=scope,
        author_id=user.id,
        title=data.title,
        content=data.content,
        post_type="notice" if scope == "service" else "general",
        is_notice=scope == "service",
        is_anonymous=data.is_anonymous if scope == "global" else False,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return get_post(db, scope, post.id)


def update_post(
    db: Session,
    scope: str,
    post_id: str,
    user: User,
    data: PostUpdate,
    is_platform_editor: bool,
) -> dict:
    post = db.query(Post).filter(
        Post.id == post_id,
        Post.board_scope == scope,
        Post.is_deleted.is_(False),
    ).first()
    if not post:
        raise LookupError("게시글을 찾을 수 없습니다.")
    if post.author_id != user.id and not is_platform_editor:
        raise PermissionError("게시글 수정 권한이 없습니다.")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(post, field, value)
    db.commit()
    return get_post(db, scope, post.id)


def delete_post(
    db: Session, scope: str, post_id: str, user: User, is_platform_editor: bool
) -> None:
    post = db.query(Post).filter(
        Post.id == post_id,
        Post.board_scope == scope,
        Post.is_deleted.is_(False),
    ).first()
    if not post:
        raise LookupError("게시글을 찾을 수 없습니다.")
    if post.author_id != user.id and not is_platform_editor:
        raise PermissionError("게시글 삭제 권한이 없습니다.")
    post.is_deleted = True
    db.commit()


def create_comment(db: Session, scope: str, post_id: str, user: User, content: str) -> Comment:
    if scope != "global":
        raise PermissionError("전체게시판에만 댓글을 작성할 수 있습니다.")
    post = db.query(Post.id).filter(
        Post.id == post_id, Post.board_scope == scope, Post.is_deleted.is_(False)
    ).first()
    if not post:
        raise LookupError("게시글을 찾을 수 없습니다.")
    comment = Comment(post_id=post_id, author_id=user.id, content=content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def update_comment(
    db: Session, post_id: str, comment_id: str, user: User, content: str,
    is_platform_editor: bool,
) -> Comment:
    comment = db.query(Comment).join(Post, Comment.post_id == Post.id).filter(
        Comment.id == comment_id,
        Comment.post_id == post_id,
        Comment.is_deleted.is_(False),
        Post.board_scope == "global",
        Post.is_deleted.is_(False),
    ).first()
    if not comment:
        raise LookupError("댓글을 찾을 수 없습니다.")
    if comment.author_id != user.id and not is_platform_editor:
        raise PermissionError("댓글 수정 권한이 없습니다.")
    comment.content = content
    db.commit()
    db.refresh(comment)
    return comment


def delete_comment(
    db: Session, post_id: str, comment_id: str, user: User, is_platform_editor: bool
) -> None:
    comment = db.query(Comment).join(Post, Comment.post_id == Post.id).filter(
        Comment.id == comment_id,
        Comment.post_id == post_id,
        Comment.is_deleted.is_(False),
        Post.board_scope == "global",
        Post.is_deleted.is_(False),
    ).first()
    if not comment:
        raise LookupError("댓글을 찾을 수 없습니다.")
    if comment.author_id != user.id and not is_platform_editor:
        raise PermissionError("댓글 삭제 권한이 없습니다.")
    comment.is_deleted = True
    db.commit()


def create_report(
    db: Session,
    reporter_id: str,
    post_id: str | None,
    comment_id: str | None,
    reason: str,
) -> ContentReport:
    if post_id and not db.query(Post.id).filter(
        Post.id == post_id, Post.is_deleted.is_(False)
    ).first():
        raise LookupError("신고할 게시글을 찾을 수 없습니다.")
    if comment_id and not db.query(Comment.id).filter(
        Comment.id == comment_id, Comment.is_deleted.is_(False)
    ).first():
        raise LookupError("신고할 댓글을 찾을 수 없습니다.")
    report = ContentReport(
        reporter_id=reporter_id,
        post_id=post_id,
        comment_id=comment_id,
        reason=reason.strip(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def list_reports(db: Session, page: int, size: int, report_status: str | None) -> dict:
    query = db.query(ContentReport)
    if report_status:
        query = query.filter(ContentReport.status == report_status)
    total = query.count()
    reports = query.order_by(ContentReport.created_at.desc()).offset(
        (page - 1) * size
    ).limit(size).all()
    return {
        "items": reports,
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }


def resolve_report(
    db: Session, report_id: str, actor_user_id: str, report_status: str
) -> ContentReport:
    report = db.query(ContentReport).filter(ContentReport.id == report_id).first()
    if not report:
        raise LookupError("신고를 찾을 수 없습니다.")
    report.status = report_status
    report.resolved_by = actor_user_id
    report.updated_at = utc_now_naive()
    db.commit()
    db.refresh(report)
    return report
