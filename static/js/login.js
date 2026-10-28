document.addEventListener("DOMContentLoaded", () => {
    const loginForm = document.getElementById('loginForm');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const togglePassword = document.getElementById('togglePassword');
    const signInButton = document.getElementById('signInButton');
    const buttonText = document.getElementById('buttonText');
    const loginMessage = document.getElementById('loginMessage');
    
    const emailContainer = document.getElementById('emailContainer');
    const passwordContainer = document.getElementById('passwordContainer');
    const emailError = document.getElementById('emailError');
    const passwordError = document.getElementById('passwordError');

    // Toggle Password Visibility
    togglePassword.addEventListener('click', () => {
        const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
        passwordInput.setAttribute('type', type);
        togglePassword.innerHTML = type === 'password' 
            ? '<i class="fa-regular fa-eye"></i>' 
            : '<i class="fa-regular fa-eye-slash"></i>';
    });

    // Handle Login Submission
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Reset UI
        loginMessage.textContent = '';
        loginMessage.className = 'login-message';
        emailContainer.classList.remove('invalid');
        passwordContainer.classList.remove('invalid');
        emailError.textContent = '';
        passwordError.textContent = '';

        const username = usernameInput.value.trim();
        const password = passwordInput.value;

        // Validation
        if (!username) {
            emailContainer.classList.add('invalid');
            emailError.textContent = "Username is required";
            return;
        }
        if (!password) {
            passwordContainer.classList.add('invalid');
            passwordError.textContent = "Password is required";
            return;
        }

        // Loading state
        signInButton.disabled = true;
        buttonText.textContent = "Signing in...";

        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: username, password: password })
            });

            const data = await response.json();

            if (data.success) {
                loginMessage.classList.add('success');
                loginMessage.textContent = "Login successful. Redirecting...";
                
                // Redirect based on role
                setTimeout(() => {
                    if (data.role === 'Admin') {
                        window.location.href = '/dashboard_admin';
                    } else if (data.role === 'Student') {
                        window.location.href = '/dashboard_student';
                    }
                }, 1000);

            } else {
                loginMessage.classList.add('error');
                loginMessage.textContent = data.message;
                signInButton.disabled = false;
                buttonText.textContent = "Sign In";
            }
        } catch (error) {
            loginMessage.classList.add('error');
            loginMessage.textContent = "Server error. Please try again.";
            signInButton.disabled = false;
            buttonText.textContent = "Sign In";
        }
    });
});