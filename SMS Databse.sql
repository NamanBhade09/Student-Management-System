-- ==========================================
-- STUDENT MANAGEMENT SYSTEM - DATABASE SCHEMA
-- ==========================================

CREATE DATABASE SMS;
GO

USE SMS;
GO

-- Drop tables in reverse order of dependencies to prevent foreign key errors
DROP TABLE IF EXISTS Performance;
DROP TABLE IF EXISTS TimeTable;
DROP TABLE IF EXISTS LeaveRequest;
DROP TABLE IF EXISTS Task;
DROP TABLE IF EXISTS StudentAttendanceSchedule;
DROP TABLE IF EXISTS AttendanceStatus;
DROP TABLE IF EXISTS Attendance;
DROP TABLE IF EXISTS Holiday;
DROP TABLE IF EXISTS Student;
DROP TABLE IF EXISTS Admin;
DROP TABLE IF EXISTS users;
GO

-- ==========================================
-- TABLES
-- ==========================================

CREATE TABLE users (
    user_id INT PRIMARY KEY identity(1,1),
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARBINARY(255) NOT NULL,
    role VARCHAR(20) NOT NULL -- 'Student' or 'Admin'
);

CREATE TABLE Admin (
    admin_id INT PRIMARY KEY identity(1,1),
    user_id INT UNIQUE,
    username VARCHAR(50) NOT NULL unique,
    mobile_no VARCHAR(15),
    email VARCHAR(100) UNIQUE NOT NULL,
    dob DATE,
    gender VARCHAR(10) not null,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE Student (
    student_id INT PRIMARY KEY identity(1,1),
    user_id INT UNIQUE,
    firstname VARCHAR(50) NOT NULL,
    lastname VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    mobile_no VARCHAR(15),
    gender VARCHAR(10),
    dob DATE,
    city VARCHAR(50) not null,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE StudentAttendanceSchedule (
    student_id INT PRIMARY KEY,
    start_time TIME(0) NOT NULL,
    end_time TIME(0) NOT NULL,
    CONSTRAINT FK_StudentAttendanceSchedule_Student
        FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);

CREATE TABLE Attendance (
    attendance_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL,
    clock_in_time DATETIME,
    clock_out_time DATETIME,
    working_hours AS CAST(DATEDIFF(MINUTE, clock_in_time, clock_out_time) / 60.0 AS DECIMAL(5,2)),
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);

-- Admin-set daily attendance status (Present / Absent / Late / Half-day).
CREATE TABLE AttendanceStatus (
    student_id INT NOT NULL,
    attendance_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('Present','Absent','Late','Half-day')),
    PRIMARY KEY (student_id, attendance_date),
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);

CREATE TABLE Holiday (
    holiday_date DATE PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

-- Updated Task table with fields for the new Tasks UI
CREATE TABLE Task (
    task_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL,
    title VARCHAR(255) not null,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed')),
    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    updated_at DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    due_date DATE NOT NULL,
    
    -- New fields added for the advanced Tasks UI
    assigned_to VARCHAR(100),
    estimated_hours DECIMAL(5,2),
    hours_logged DECIMAL(5,2) DEFAULT 0,
    
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);

CREATE TABLE LeaveRequest (
    leave_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    leave_type Varchar(50) not null,
    applied_on DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    reason TEXT,
    status VARCHAR(20) DEFAULT 'Pending', -- 'Pending', 'Approved', 'Rejected'
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);

CREATE TABLE TimeTable (
    timetable_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL,
    day_of_week VARCHAR(10) NULL,
    time_slots VARCHAR(255),
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);

CREATE TABLE Performance (
    performance_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL UNIQUE,
    overall_percentage DECIMAL(5,2),
    grade VARCHAR(10),
    total_attendance_percentage DECIMAL(5,2),
    avg_login_time TIME,
    total_tasks_completed INT,
    remaining_tasks INT,
    total_leaves INT,
    absent_without_leave INT,
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);
GO

-- ==========================================
-- INITIAL DATA (For Testing)
-- ==========================================

-- Insert an Admin user (Password is 'admin123' hashed with pbkdf2:sha256)
INSERT INTO users (username, password_hash, role) 
VALUES ('admin', 0x70626B6466323A7368613235363A3236303030303A6A396A6C4B705A6B4759676A61306C3A3334653763643738363137313733616437363439393334356639363937366635, 'Admin');

INSERT INTO Admin (user_id, username, email, gender)
VALUES (1, 'admin', 'admin@campus.com', 'Other');

-- Insert a Holiday (So the calendar has something to show)
INSERT INTO Holiday (holiday_date, name) VALUES ('2026-12-25', 'Christmas Day');
INSERT INTO Holiday (holiday_date, name) VALUES ('2027-01-01', 'New Year');


SELECT * FROM users;
SELECT * FROM Admin;
SELECT * FROM Student;
SELECT * FROM StudentAttendanceSchedule;
SELECT * FROM Attendance;
SELECT * FROM AttendanceStatus;
SELECT * FROM Holiday;
SELECT * FROM Task;
SELECT * FROM LeaveRequest;
SELECT * FROM TimeTable;
SELECT * FROM Performance;