Create database SMS



CREATE TABLE users (
    user_id INT PRIMARY KEY identity(1,1),
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARBINARY(255) NOT NULL,
    role VARCHAR(20) NOT NULL -- Expected values: 'Student', 'Admin'
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

CREATE TABLE Attendance (
    attendance_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL,
    clock_in_time DATETIME,
    clock_out_time DATETIME,
    working_hours    AS CAST(DATEDIFF(MINUTE, clock_in_time, clock_out_time) / 60.0 AS DECIMAL(5,2)),
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);


CREATE TABLE Task (
    task_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL,
    title VARCHAR(255) not null, -- Title or brief of the task
    description TEXT,
   status       VARCHAR(20) NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'in_progress', 'completed')),
    created_at   DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    updated_at   DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    due_date     DATE    NOT NULL ,
    FOREIGN KEY (student_id)
        REFERENCES Student(student_id) ON DELETE CASCADE
);

CREATE TABLE LeaveRequest (
    leave_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    leave_type Varchar(50) not null,
    applied_on  DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    reason TEXT,
    status VARCHAR(20) DEFAULT 'Pending', -- e.g., 'Pending', 'Approved', 'Rejected'
    FOREIGN KEY (student_id) REFERENCES Student(student_id) ON DELETE CASCADE
);

CREATE TABLE TimeTable (
    timetable_id INT PRIMARY KEY identity(1,1),
    student_id INT NOT NULL,
    day_of_week   VARCHAR(10) NULL,
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

SELECT * FROM users;
SELECT * FROM Admin;
SELECT * FROM Student;
SELECT * FROM Attendance;
SELECT * FROM Task;
SELECT * FROM LeaveRequest;
SELECT * FROM TimeTable;
SELECT * FROM Performance;