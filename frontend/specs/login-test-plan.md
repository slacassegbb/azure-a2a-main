# Login Test Plan for A2A Frontend

## Application Context
You are testing the login functionality of an Agent-to-Agent (A2A) orchestration platform frontend built with Next.js.

## Authentication Endpoints
- Login: `POST /api/auth/login`
- Register: `POST /api/auth/register`
- Base URL: `http://localhost:12000` (configurable via `NEXT_PUBLIC_A2A_API_URL`)

## Login Dialog Component Structure

### Location
The login dialog is triggered by a button in the top-right corner of the application.

### Fields (Login Mode)
- **Email**: Text input for user email
- **Password**: Password input for user password
- **Submit Button**: "Login" button

### Fields (Register Mode)
- **Email**: Text input for user email
- **Password**: Password input for user password
- **Name**: Text input for user's full name
- **Role**: Text input for user's role/title
- **Description**: Textarea for user description
- **Skills**: Text input for comma-separated skills
- **Color**: Color picker for user avatar color
- **Submit Button**: "Register" button

### Mode Toggle
- Link at bottom of dialog to switch between "Login" and "Register" modes
- Text: "Need an account? Register" (in login mode)
- Text: "Already have an account? Login" (in register mode)

## Test Scenarios to Automate

### 1. Successful Login
- Navigate to the application
- Click the login button/dialog trigger
- Fill in valid email: `test@example.com`
- Fill in valid password: `password123`
- Click the "Login" button
- Verify the auth token is stored in sessionStorage
- Verify the page reloads and user is authenticated

### 2. Failed Login (Invalid Credentials)
- Navigate to the application
- Open login dialog
- Fill in email: `invalid@example.com`
- Fill in password: `wrongpassword`
- Click "Login"
- Verify error message is displayed
- Verify user is NOT authenticated

### 3. Empty Form Validation
- Navigate to the application
- Open login dialog
- Click "Login" without filling in fields
- Verify error message: "Please fill in all fields"

### 4. Register New User
- Navigate to the application
- Open login dialog
- Click "Need an account? Register"
- Verify dialog switches to register mode
- Fill in all required fields:
  - Email: `newuser@example.com`
  - Password: `securepass123`
  - Name: `Test User`
  - Role: `QA Engineer`
  - Description: `Testing the platform`
  - Skills: `testing, automation, playwright`
- Click "Register"
- Verify successful registration
- Verify auth token is stored
- Verify page reloads

### 5. Switch Between Login and Register Modes
- Open login dialog
- Verify initial mode is "Login"
- Click "Need an account? Register"
- Verify form switches to register mode with additional fields
- Click "Already have an account? Login"
- Verify form switches back to login mode

## Expected Behavior

### On Successful Authentication
1. Auth token stored in `sessionStorage` with key `auth_token`
2. Page performs `window.location.reload()`
3. Subsequent requests include the auth token

### On Failed Authentication
1. Error message displayed in the dialog
2. User remains on login screen
3. No token stored
4. Form remains populated (except password cleared)

## Technical Notes
- Frontend runs on: `http://localhost:3000` (Next.js default)
- Backend API: `http://localhost:12000`
- State management: React hooks (useState)
- Storage: sessionStorage for JWT tokens
- Response includes: `access_token`, `user_info` object
