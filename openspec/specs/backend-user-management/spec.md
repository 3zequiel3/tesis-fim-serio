## ADDED Requirements

### Requirement: Admin can list all admin users (RN-45)
The system SHALL allow an authenticated admin to retrieve a paginated list of all admin users. Password hashes MUST NOT be returned in any response.

#### Scenario: Admin lists users
- **WHEN** an authenticated admin sends GET /users
- **THEN** system returns a paginated list with user id, email, and created_at for each user

#### Scenario: Unauthenticated request rejected
- **WHEN** a request without a valid session token is sent to GET /users
- **THEN** system returns 401

#### Scenario: Non-admin request rejected
- **WHEN** a request from a non-admin user is sent to GET /users
- **THEN** system returns 403

### Requirement: Admin can create an additional admin user (RN-45)
The system SHALL allow an authenticated admin to create a new admin account. The new password SHALL be hashed with Argon2id. Every creation SHALL be recorded in the audit_log.

#### Scenario: Successful admin creation
- **WHEN** an authenticated admin sends POST /users with a valid email and password
- **THEN** system creates the user, records an audit_log entry with action "user_created", and returns 201 with the new user's id and email

#### Scenario: Duplicate email rejected
- **WHEN** POST /users is called with an email that already exists in the system
- **THEN** system returns 409

#### Scenario: Weak password rejected
- **WHEN** POST /users is called with a password shorter than the minimum length
- **THEN** system returns 422 with a validation error

#### Scenario: Creation recorded in audit log
- **WHEN** an admin successfully creates a new user via POST /users
- **THEN** an audit_log entry is written with actor_id of the requesting admin and target_id of the new user
