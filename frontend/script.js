async function sendMsg() {
  let input = document.getElementById("user-input");
  let message = input.value;
  if (!message.trim()) return;
  
  input.value = "";

  addMessage(message, "user");

  try {
      const res = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: message }),
      });

      if (!res.ok) {
          throw new Error("Network response was not ok");
      }

      const data = await res.json();

      addMessage(data.answer, "bot");

      if (data.citations && data.citations.length > 0) {
        data.citations.forEach(c => {
          addMessage(`[Source: ${c.file}] → "${c.quote}"`, "citation");
        });
      }
  } catch (err) {
      addMessage("Error connecting to backend.", "bot");
      console.error(err);
  }
}

function addMessage(msg, cls) {
  const chat = document.getElementById("chat");
  const div = document.createElement("div");
  div.className = cls;
  div.innerText = msg;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight; // Auto scroll
}

// Allow Enter key to send
document.getElementById("user-input").addEventListener("keypress", function(event) {
  if (event.key === "Enter") {
    sendMsg();
  }
});
