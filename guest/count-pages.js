// Prints the number of pages of the document given as the first argument.
var doc = Document.openDocument(scriptArgs[0]);
print(doc.countPages());
