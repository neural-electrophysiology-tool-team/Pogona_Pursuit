export function randomRange (min, max) {
	while (true) {
		let randomNum = Math.floor(Math.random() * (max - min) + min)
		if (randomNum !== 0)
			return randomNum
	}
}

export const distance = (x1, y1, x2, y2) => Math.sqrt(Math.pow(x2 - x1, 2) + Math.pow(y2 - y1, 2))