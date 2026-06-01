const crypto = require('crypto');

const data = "615f01010e4c76a5-70af8049e10dca8de2106c09-f87502f6151f7f6407530ef40dcd11d86b545357f8357a160f34acb8b183907087525acfbb8c76a2";
const parts = data.split("-");
const salt = Buffer.from(parts[0], 'hex');
const iv = Buffer.from(parts[1], 'hex');
const ciphertext = Buffer.from(parts[2], 'hex');
const password = "player";

crypto.pbkdf2(password, salt, 1000, 32, 'sha256', (err, key) => {
    if (err) throw err;
    try {
        const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
        // AES-GCM requires the authentication tag. In WebCrypto, the last 16 bytes of the ciphertext are the auth tag!
        const authTag = ciphertext.slice(ciphertext.length - 16);
        const encrypted = ciphertext.slice(0, ciphertext.length - 16);
        decipher.setAuthTag(authTag);
        let decrypted = decipher.update(encrypted, null, 'utf8');
        decrypted += decipher.final('utf8');
        console.log("Decrypted:", decrypted);
    } catch(e) {
        console.error("Decryption failed:", e.message);
    }
});
