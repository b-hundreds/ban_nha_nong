"use strict";

document.addEventListener("DOMContentLoaded", init);

function init() {
  var modal = document.getElementById("loginModal");
  var openBtns = [
    document.getElementById("navLoginBtn"),
    document.getElementById("heroLoginBtn"),
    document.getElementById("ctaLoginBtn"),
  ];
  var closeBtn = document.getElementById("modalClose");
  var loginForm = document.getElementById("loginForm");
  var loginError = document.getElementById("loginError");

  openBtns.forEach(function (btn) {
    if (!btn) return;
    btn.addEventListener("click", function () { openModal(); });
  });

  if (closeBtn) {
    closeBtn.addEventListener("click", function () { closeModal(); });
  }

  modal.addEventListener("click", function (e) {
    if (e.target === modal) closeModal();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });

  if (loginForm) {
    loginForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var email = document.getElementById("loginEmail").value.trim();
      var password = document.getElementById("loginPassword").value;
      if (!email || !password) {
        showError("Vui lòng nhập email và mật khẩu.");
        return;
      }
      showError("Chức năng đăng nhập đang được hoàn thiện. Bác hãy trò chuyện ẩn danh trước nhé.");
    });
  }

  function openModal() {
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    var firstInput = modal.querySelector("input");
    if (firstInput) firstInput.focus();
  }

  function closeModal() {
    modal.hidden = true;
    document.body.style.overflow = "";
    if (loginError) loginError.hidden = true;
  }

  function showError(msg) {
    if (!loginError) return;
    loginError.textContent = msg;
    loginError.hidden = false;
  }
}
