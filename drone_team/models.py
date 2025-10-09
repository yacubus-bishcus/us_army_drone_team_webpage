# drone_team/models.py 
from .extensions import db
from datetime import datetime


class NewsArticle(db.Model):
    __tablename__ = "news_articles"

    id = db.Column(db.String(32), primary_key=True)
    url = db.Column(db.String(1024), nullable=False)
    title = db.Column(db.String(512), nullable=False)
    summary = db.Column(db.Text)
    image_url = db.Column(db.String(1024))
    added_by = db.Column(db.String(128), nullable=False, index=True)
    added_at = db.Column(db.DateTime, nullable=False, index=True)


class WhitePaper(db.Model):
    __tablename__ = "white_papers"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False, index=True)
    authors = db.Column(db.String(300))
    year = db.Column(db.Integer, index=True)
    tags = db.Column(db.String(300), index=True)         # comma-separated
    abstract = db.Column(db.Text)
    filename = db.Column(db.String(300), nullable=False)
    filesize = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, index=True, nullable=False)

class SoftwareFile(db.Model):
    __tablename__ = "software_files"
    id = db.Column(db.Integer, primary_key=True)
    # 'cad' or 'uas'
    category = db.Column(db.String(16), index=True, nullable=False)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)
    version = db.Column(db.String(64))
    license = db.Column(db.String(128))
    filetype = db.Column(db.String(64), index=True)   # e.g., STL, STEP, SLDPART, Firmware, Python, MAVLink, etc.
    tags = db.Column(db.String(300), index=True)      # comma-separated
    filename = db.Column(db.String(300), nullable=False)
    filesize = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    downloads = db.Column(db.Integer, default=0, nullable=False)

class AAR(db.Model):
    __tablename__ = "aars"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(280), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, index=True)  # tie to your users table if you have one
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # convenience, not persisted:
    @property
    def score(self):
        # optional: denormalized column if you want; otherwise compute from votes
        return sum(v.value for v in self.votes)

class AARVote(db.Model):
    __tablename__ = "aar_votes"
    id = db.Column(db.Integer, primary_key=True)
    aar_id = db.Column(db.Integer, db.ForeignKey("aars.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    value = db.Column(db.Integer, nullable=False)  # +1 or -1
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("aar_id", "user_id", name="uq_aar_vote_user"),
    )

    aar = db.relationship("AAR", backref=db.backref("votes", cascade="all, delete-orphan"))

class AARComment(db.Model):
    __tablename__ = "aar_comments"
    id = db.Column(db.Integer, primary_key=True)
    aar_id = db.Column(db.Integer, db.ForeignKey("aars.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    aar = db.relationship("AAR", backref=db.backref("comments", cascade="all, delete-orphan"))