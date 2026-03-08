
// Fetch update count from the server — only runs if target elements exist on this page
const updateCountElement = document.getElementById('updateCount');
const updateLink = document.getElementById('updateLink');

if (updateCountElement || updateLink) {
    fetch('https://read.realbible.tech/update_count/')
        .then(response => response.json())
        .then(data => {
            const updateCount = data.updateCount;

            if (updateLink) {
                updateLink.addEventListener('click', () => {
                    window.location.href = 'https://read.realbible.tech/updates/';
                });
            }

            if (updateCountElement) {
                updateCountElement.textContent = updateCount;
            }
        })
        .catch(error => console.error('Error:', error));
}
