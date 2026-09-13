async function authRequest(endpoint, body) {
  const response = await fetch(endpoint, {
    method: "POST",

    credentials: "same-origin",

    cache: "no-store",

    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },

    body: JSON.stringify(body),
  });

  let data = {};

  try {
    data = await response.json();
  } catch (_) {}

  if (!response.ok) {
    throw new Error(
      data.error || "request_failed"
    );
  }

  return data;
}


function showMessage(text, isError = false) {
  const node =
    document.querySelector("#auth-message");

  if (!node) {
    return;
  }

  node.textContent = text;

  node.style.color =
    isError
      ? "#d6a4a4"
      : "#D4AF37";
}


function clearLoginFields() {
  const form =
    document.querySelector("#auth-form");

  if (
    !form ||
    form.dataset.mode !== "login"
  ) {
    return;
  }

  const email =
    form.elements.email;

  const password =
    form.elements.password;


  if (email) {
    email.value = "";
    email.defaultValue = "";
  }


  if (password) {
    password.value = "";
    password.defaultValue = "";
  }
}


async function submitAuth(event) {
  event.preventDefault();

  const form =
    event.currentTarget;

  const mode =
    form.dataset.mode;

  const email =
    form.elements.email.value.trim();

  const password =
    form.elements.password.value;


  if (!email || !password) {
    showMessage(
      "Enter your email and password.",
      true
    );

    return;
  }


  const button =
    form.querySelector("button");

  button.disabled = true;


  showMessage(
    mode === "register"
      ? "Creating account…"
      : "Signing in…"
  );


  try {

    await authRequest(
      `/api/auth/${mode}`,
      {
        email,
        password,
      }
    );


    /*
     * Remove the password from the DOM
     * immediately after successful authentication.
     */
    if (form.elements.password) {
      form.elements.password.value = "";
    }


    /*
     * Replace login page in browser history.
     */
    window.location.replace(
      "/dashboard"
    );

  } catch (error) {

    /*
     * Never leave the entered password
     * sitting in the field after a failed login.
     */
    if (form.elements.password) {
      form.elements.password.value = "";

      form.elements.password.focus();
    }


    const messages = {

      invalid_email:
        "Enter a valid email address.",

      password_too_short:
        "Password must contain at least 10 characters.",

      account_exists:
        "An account with this email already exists.",

      invalid_credentials:
        "Email or password is incorrect.",
    };


    showMessage(
      messages[error.message] ||
        "Unable to continue.",
      true
    );

  } finally {

    button.disabled = false;

  }
}


document
  .querySelector("#auth-form")
  ?.addEventListener(
    "submit",
    submitAuth
  );


/*
 * Clear credentials whenever
 * the login page loads normally.
 */
document.addEventListener(
  "DOMContentLoaded",
  () => {

    clearLoginFields();


    /*
     * Browsers/password managers sometimes
     * autofill shortly after DOMContentLoaded.
     */
    setTimeout(
      clearLoginFields,
      50
    );

    setTimeout(
      clearLoginFields,
      250
    );

  }
);


/*
 * Also clear fields when the browser restores
 * the page using back/forward cache.
 */
window.addEventListener(
  "pageshow",
  () => {

    clearLoginFields();

  }
);