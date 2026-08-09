const form = document.getElementById("authForm");
const heading = document.getElementById("authHeading");
const sub = document.getElementById("authSub");
const submitBtn = document.getElementById("authSubmit");
const toggleText = document.getElementById("toggleText");
const toggleBtn = document.getElementById("toggleBtn");
const errorBox = document.getElementById("authError");
const passwordInput = document.getElementById("password");

let mode = "login"; // "login" | "register"

function applyMode() {
  const isLogin = mode === "login";
  heading.textContent = isLogin ? "Welcome back" : "Create your account";
  sub.textContent = isLogin
    ? "Log in to pick up where you left off."
    : "Just an email and password — no verification step for now.";
  submitBtn.textContent = isLogin ? "Log in" : "Register";
  toggleText.textContent = isLogin ? "Don't have an account?" : "Already have an account?";
  toggleBtn.textContent = isLogin ? "Register" : "Log in";
  passwordInput.autocomplete = isLogin ? "current-password" : "new-password";
  errorBox.hidden = true;
}

toggleBtn.addEventListener("click", () => {
  mode = mode === "login" ? "register" : "login";
  applyMode();
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorBox.hidden = true;
  submitBtn.disabled = true;

  const email = document.getElementById("email").value.trim();
  const password = passwordInput.value;

  try {
    const res = await fetch(mode === "login" ? "/api/login" : "/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    window.location.href = "/";
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.hidden = false;
  } finally {
    submitBtn.disabled = false;
  }
});

applyMode();
