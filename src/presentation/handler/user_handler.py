from src.domain.services.user_service import UserService

user_service = UserService()



def get_all_user_info_from_db():
    """
    Get all user information.
    
    This endpoint returns all user information from the database.
    """

    users = user_service.get_all_users()
    
    return users


def sign_up_user(raw_user_data):
    """
    Sign up a new user.
    
    This endpoint handles the creation of a new user in both the database and Firebase.
    """

    sign_up_data = user_service.sign_up(raw_user_data)  # This will handle both DB and Firebase user creation

    return sign_up_data  # Return the result of the sign-up operation, which could be a success message or user data


def log_in_user(raw_user_data):
    """
    Log in a user.
    
    This endpoint handles user authentication and returns user data if successful.
    """

    login_data = user_service.log_in(raw_user_data)  # This will handle user authentication

    return login_data  # Return the result of the login operation, which could be user data or an error message
    