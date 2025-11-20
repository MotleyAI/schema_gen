"""
Example usage of LLM-driven SQLAlchemy schema generation.

This script demonstrates how to use the schema_gen module to generate
database schemas from natural language prompts using the validation loop pattern.

Run with:
    python example.py

Requirements:
    - OPENAI_API_KEY environment variable must be set
    - Dependencies installed via: poetry install
"""

import os
import logging
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI

from schema_gen import generate_sqlalchemy_models_from_prompt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    """Generate schema from natural language using LLM."""
    print("\n" + "=" * 80)
    print("LLM-Driven Database Schema Generation Example")
    print("=" * 80)

    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\nError: OPENAI_API_KEY environment variable not set")
        print("Please set your OpenAI API key:")
        print("  export OPENAI_API_KEY='your-api-key-here'")
        return

    # Initialize LLM
    llm = ChatOpenAI(model="gpt-4o", api_key=api_key)

    # Define schema prompt
    prompt = """
    Create a database schema for a project management application with:
    - Users who can create projects
    - Projects that have tasks
    - Tasks that can be assigned to users
    - Comments on tasks

    Include appropriate foreign keys, timestamps, and ON DELETE CASCADE where appropriate.
    """

    print("\nPrompt:")
    print(prompt)
    print("\nGenerating schema with LLM...")

    try:
        # Generate schema using validation loop pattern
        schema = generate_sqlalchemy_models_from_prompt(
            prompt=prompt,
            language_model=llm,
        )

        print(f"\nGenerated schema with {len(schema.tables)} tables:")
        for table in schema.tables:
            print(f"  - {table.name}")

        # Convert to ORM classes
        orm_classes = schema.to_orm_classes()
        print(f"\nCreated {len(orm_classes)} ORM classes:")
        for name in orm_classes.keys():
            print(f"  - {name}")

        # Create SQLite database
        db_path = "project_management.db"
        engine = create_engine(f"sqlite:///{db_path}", echo=False)

        # Get Base class from any ORM class
        if not orm_classes:
            raise ValueError("No ORM classes found in schema generation - expected at least one")
        Base = list(orm_classes.values())[0].__bases__[0]
        Base.metadata.create_all(engine)

        print(f"\nCreated database: {db_path}")
        print("\nTables created:")
        inspector = inspect(engine)
        for table_name in inspector.get_table_names():
            print(f"  - {table_name}")
            columns = inspector.get_columns(table_name)
            for col in columns:
                print(f"      {col['name']}: {col['type']}")

        # Populate with sample data
        print("\nPopulating database with sample data...")
        session = Session(engine)

        # Extract ORM classes
        User = orm_classes.get("User")
        Project = orm_classes.get("Project")
        Task = orm_classes.get("Task")
        Comment = orm_classes.get("Comment")

        if User and Project and Task:
            # Create users
            user1 = User(username="alice", email="alice@example.com")
            user2 = User(username="bob", email="bob@example.com")
            session.add_all([user1, user2])
            session.commit()
            print(f"  Created users: {user1.username}, {user2.username}")

            # Create projects
            project1 = Project(
                name="Website Redesign",
                description="Redesign company website",
                owner_id=user1.id,
            )
            project2 = Project(
                name="Mobile App",
                description="Build mobile app",
                owner_id=user2.id,
            )
            session.add_all([project1, project2])
            session.commit()
            print(f"  Created projects: {project1.name}, {project2.name}")

            # Create tasks
            task1 = Task(
                title="Design mockups",
                description="Create UI mockups",
                project_id=project1.id,
                assigned_to_id=user1.id,
                status="in_progress",
            )
            task2 = Task(
                title="Setup backend",
                description="Initialize backend API",
                project_id=project1.id,
                assigned_to_id=user2.id,
                status="todo",
            )
            task3 = Task(
                title="Create login flow",
                description="Implement authentication",
                project_id=project2.id,
                assigned_to_id=user1.id,
                status="done",
            )
            session.add_all([task1, task2, task3])
            session.commit()
            print(f"  Created {3} tasks")

            # Create comments if Comment class exists
            if Comment:
                comment1 = Comment(
                    task_id=task1.id,
                    user_id=user2.id,
                    content="Looks great! Can we add dark mode?",
                )
                comment2 = Comment(
                    task_id=task1.id,
                    user_id=user1.id,
                    content="Sure, I'll add that to the next iteration.",
                )
                session.add_all([comment1, comment2])
                session.commit()
                print(f"  Created {2} comments")

            # Query and display data
            print("\nSample data inserted successfully!")
            print("\nExample queries:")

            # Query 1: All projects with their owners
            print("\n1. Projects and owners:")
            projects = session.query(Project).all()
            for proj in projects:
                owner = session.query(User).filter_by(id=proj.owner_id).first()
                print(f"   {proj.name} (owned by {owner.username})")

            # Query 2: Tasks for first project
            print("\n2. Tasks in first project:")
            tasks = session.query(Task).filter_by(project_id=project1.id).all()
            for task in tasks:
                assignee = session.query(User).filter_by(id=task.assigned_to_id).first()
                print(f"   [{task.status}] {task.title} (assigned to {assignee.username})")

            # Query 3: Comments on first task if Comment exists
            if Comment:
                print("\n3. Comments on first task:")
                comments = session.query(Comment).filter_by(task_id=task1.id).all()
                for comment in comments:
                    commenter = session.query(User).filter_by(id=comment.user_id).first()
                    print(f"   {commenter.username}: {comment.content}")

        session.close()
        engine.dispose()

        print("\n" + "=" * 80)
        print("Example complete!")
        print("=" * 80 + "\n")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        print("\nThis may occur if dependencies are not installed or configured correctly.")
        print("Run: poetry install")


if __name__ == "__main__":
    main()
