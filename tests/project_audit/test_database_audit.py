from db import database


def test_database_functions():

    required = [

        "init_db",

        "load_case",
        "add_case",

        "get_documents",
        "update_document",

        "add_task",
        "update_task",

        "log_case_event",

        "create_user",
        "get_user",

    ]


    missing=[]


    for name in required:

        if not hasattr(database,name):
            missing.append(name)


    assert not missing, f"Missing database functions: {missing}"



def test_database_connection():

    with database.get_db_connection() as conn:

        cursor=conn.cursor()

        cursor.execute(
            "SELECT 1"
        )

        result=cursor.fetchone()


    assert result[0]==1